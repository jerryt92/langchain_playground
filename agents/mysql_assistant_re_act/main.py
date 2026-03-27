import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from agents.mysql_assistant_re_act.mysql_ops import MySQLConnectionConfig, MySQLOps
from lib.agent_runtime import InteractiveAgentRuntime
from lib.langchain_model import chat_anthropic

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.env_loader import load_env_config
import mysql_ops
from tools import build_tools

AGENT_DIR = Path(__file__).resolve().parent


@wrap_tool_call
def handle_tool_errors(request, handler):
    try:
        return handler(request)
    except Exception as exc:
        return ToolMessage(
            content=f"工具执行失败：{exc}",
            tool_call_id=request.tool_call["id"],
        )


def _parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _message_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    return str(content).strip()


# 打印Agent最新的message
def _print_chunk(previous_count: int, chunk: dict[str, Any]) -> int:
    messages = chunk.get("messages")
    for message in messages[previous_count:]:
        if isinstance(message, AIMessage):
            if message.content[0].get("thinking"):
                print("\n=== 推理 ===")
                print(message.content[0].get("thinking"))
        if isinstance(message, AIMessage) and message.tool_calls:
            print("\n=== 工具调用 ===")
            for tool_call in message.tool_calls:
                args = json.dumps(tool_call.get("args", {}), ensure_ascii=False)
                print(f"- {tool_call['name']}: {args}")
            continue

        if isinstance(message, ToolMessage):
            print("\n=== 工具结果 ===")
            print(message.content)
            continue

        if isinstance(message, AIMessage):
            text = _message_to_text(message.content)
            if text:
                print("\n=== 模型输出 ===")
                print(text)

    return len(messages)


def _extract_final_answer(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _message_to_text(message.content)
            if text:
                return text
    return "已完成，但模型没有返回可显示内容。"


def build_system_prompt() -> str:
    mode_text = (
        "当前允许写操作，但每次调用 run_sql 仍然只能执行一条 SQL。"
        if mysql_ops.ops.allow_write
        else "当前是只读模式，run_sql 只允许执行单条 SELECT 或 WITH 查询。"
    )
    lines = [
        "你是一个会使用工具的 MySQL 智能体。",
        "你需要根据用户问题反复调用工具，自主探索数据库、表结构和查询结果，然后再给出最终答复。",
        "规则如下：",
        "1. 优先使用工具获取事实，不要猜测库名、表名、字段名。",
        "2. 如果用户问题涉及库、表、字段信息，先调用 list_databases、list_tables、get_table_schema。",
        "3. 调用 run_sql 时只允许传入一条 SQL，且除了 information_schema 之外，业务表尽量显式写成 `数据库名.表名`。",
        "4. 不要使用 `USE 数据库名`。",
        f"5. {mode_text}",
        "6. 最终答复使用中文，简洁说明结论；如果执行了 SQL，请附上关键 SQL 或结果摘要。",
    ]
    if mysql_ops.ops.include_tables:
        lines.append(
            "当前启用了 INCLUDE_TABLES 过滤，仅这些表允许访问："
            + ", ".join(mysql_ops.ops.include_tables)
        )
    return "\n".join(lines)


def build_assistant() -> tuple[CompiledStateGraph, bool]:
    env = load_env_config(PROJECT_ROOT, AGENT_DIR)
    allow_write = _parse_bool(env.get("ALLOW_WRITE"), default=False)
    include_tables = _parse_csv(env.get("INCLUDE_TABLES"))
    print_model_output = _parse_bool(env.get("PRINT_MODEL_OUTPUT"), default=False)
    mysql_connection_config = MySQLConnectionConfig(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", None),
        charset=env.get("MYSQL_CHARSET", "utf8mb4"),
        connect_timeout=int(env.get("MYSQL_CONNECT_TIMEOUT", "30")),
        read_timeout=int(env.get("MYSQL_READ_TIMEOUT", "30")),
        write_timeout=int(env.get("MYSQL_WRITE_TIMEOUT", "30")),
    )
    mysql_ops.ops = MySQLOps(
        mysql_connection_config=mysql_connection_config,
        allow_write=allow_write,
        include_tables=include_tables,
    )

    # 这里会创建一个 ReAct 模式的 agent （需要使用支持深度思考的模型）
    # 由于阿里云百炼平台的OpenAI接口是通过非标准的方式返回的深度思考内容，而Anthropic接口则遵循了标准的深度思考实现，因此需要使用Anthropic接口
    agent = create_agent(
        model=chat_anthropic,
        tools=build_tools(),
        system_prompt=build_system_prompt(),
        middleware=[handle_tool_errors],
        name="MySQL 智能助手",
    )
    return agent, print_model_output


def run_one_question(
    question: str,
    agent: CompiledStateGraph,
    conversation: list[BaseMessage],
    print_model_output: bool,
) -> list[BaseMessage]:
    input_messages = [*conversation, HumanMessage(content=question)]

    if print_model_output:
        latest_chunk: dict[str, Any] | None = None
        # 剔除打印过的消息
        printed_count = len(input_messages)
        # agent.stream会返回一个迭代器，直到agent任务结束，迭代器才会声明结束，故而跳出for循环
        # 迭代器中的chunk中包含了agent最新的消息和所有历史消息，该机制方便观察模型输出，和agent状态
        for chunk in agent.stream({"messages": input_messages}, stream_mode="values"):
            printed_count = _print_chunk(printed_count, chunk)
            latest_chunk = chunk
        print("\n=== 运行结束 ===")
        if latest_chunk is None:
            raise RuntimeError("智能体没有返回任何结果。")
        final_messages = latest_chunk["messages"]
    else:
        result = agent.invoke({"messages": input_messages})
        final_messages = result["messages"]
    return final_messages


class ReActAgentRuntime(InteractiveAgentRuntime):
    def __init__(self, agent: CompiledStateGraph, print_model_output: bool):
        self.agent = agent
        self.print_model_output = print_model_output
        self.conversation: list[BaseMessage] = []

    def send_message(self, message: str) -> str:
        self.conversation = run_one_question(
            message,
            self.agent,
            self.conversation,
            self.print_model_output,
        )
        return _extract_final_answer(self.conversation)

    def reset(self) -> None:
        self.conversation = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangChain create_agent + MySQL 工具智能体 Demo")
    parser.add_argument(
        "question",
        nargs="*",
        help='单次提问内容。例如：python agents/mysql_assistant_re_act/main.py "统计每个库的表数量"',
    )
    return parser.parse_args()


def init() -> tuple[CompiledStateGraph, bool] | None:
    try:
        return build_assistant()
    except Exception as exc:
        print(f"[初始化失败] {exc}", file=sys.stderr)
        return None


def main() -> int | None:
    runtime = init()
    if not runtime:
        return 1

    agent, print_model_output = runtime
    interactive_runtime = ReActAgentRuntime(agent, print_model_output)
    args = parse_args()
    one_shot_question = " ".join(args.question).strip()
    if one_shot_question:
        try:
            return interactive_runtime.run_one_shot(one_shot_question)
        except Exception as exc:
            traceback.TracebackException.from_exception(exc).print()
            return 1

    try:
        return interactive_runtime.run_interactive()
    except Exception as exc:
        traceback.TracebackException.from_exception(exc).print()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
