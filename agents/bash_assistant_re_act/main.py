import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from agents.bash_assistant_re_act import shell_ops
from agents.bash_assistant_re_act.shell_ops import ShellConfig, ShellOps
from lib.agent_runtime import InteractiveAgentRuntime
from lib.env_loader import load_env_config
from lib.langchain_model import chat_anthropic

from agents.bash_assistant_re_act.tools import build_tools

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


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _iter_text_parts(content: Any) -> list[str]:
    if isinstance(content, str):
        text = content.strip()
        return [text] if text else []
    if not isinstance(content, list):
        text = str(content).strip()
        return [text] if text else []

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            text = item.strip()
            if text:
                parts.append(text)
            continue
        if isinstance(item, dict):
            text = item.get("text")
            if text:
                normalized = str(text).strip()
                if normalized:
                    parts.append(normalized)
    return parts


def _message_to_text(content: Any) -> str:
    return "\n".join(_iter_text_parts(content)).strip()


def _print_chunk(previous_count: int, chunk: dict[str, Any]) -> int:
    messages = chunk.get("messages", [])
    for message in messages[previous_count:]:
        if isinstance(message, AIMessage) and isinstance(message.content, list):
            thinking_parts: list[str] = []
            for item in message.content:
                if isinstance(item, dict) and item.get("thinking"):
                    thinking_parts.append(str(item["thinking"]).strip())
            if thinking_parts:
                print("\n=== 推理 ===")
                print("\n".join(part for part in thinking_parts if part))

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
    policy = shell_ops.ops.describe_policy()
    return "\n".join(
        [
            "你是一个会使用工具的命令行助手。",
            "你需要根据用户目标，自主查看目录、读取文件、搜索文本、在合适的工作目录执行命令行命令，然后再给出最终答复。",
            "规则如下：",
            "1. 先用 list_dir、read_file、search_files 获取事实，再决定是否调用 run_command。",
            "2. 除非任务确实需要执行命令，否则优先使用 Python 工具读取信息，避免无意义的 ls/cat/rg。",
            "3. 调用 run_command 时要显式提供 working_dir，并保证命令与当前任务直接相关。",
            "4. 必须根据当前操作系统选择合适的命令和语法：macOS/Linux 优先使用 POSIX shell 语法，Windows 优先使用 PowerShell 或兼容命令。",
            "5. 一次只做一小步；拿到输出后再决定下一步，不要凭空假设命令结果。",
            "6. 如果工具返回错误、超时或被安全策略拦截，需要根据错误信息调整方案，不要重复同样的危险命令。",
            f"7. 当前执行策略：{policy}",
            "8. 最终答复使用中文，简洁说明结论，并附上关键命令或关键输出摘要。",
        ]
    )


def build_assistant() -> tuple[CompiledStateGraph, bool]:
    env = load_env_config(PROJECT_ROOT, AGENT_DIR)
    print_model_output = _parse_bool(env.get("PRINT_MODEL_OUTPUT"), default=False)

    workspace_root = env.get("WORKSPACE_ROOT", str(PROJECT_ROOT)).strip() or str(PROJECT_ROOT)
    extra_allowed_roots = _parse_csv(env.get("EXTRA_ALLOWED_ROOTS"))
    extra_blocked_patterns = _parse_csv(env.get("BLOCKED_COMMAND_PATTERNS"))

    shell_ops.ops = ShellOps(
        ShellConfig(
            workspace_root=workspace_root,
            extra_allowed_roots=extra_allowed_roots,
            command_timeout_seconds=int(env.get("COMMAND_TIMEOUT_SECONDS", "30")),
            max_output_chars=int(env.get("MAX_OUTPUT_CHARS", "12000")),
            max_file_read_chars=int(env.get("MAX_FILE_READ_CHARS", "20000")),
            max_search_results=int(env.get("MAX_SEARCH_RESULTS", "100")),
            shell_executable=env.get("COMMAND_EXECUTABLE", "").strip() or None,
            extra_blocked_patterns=extra_blocked_patterns,
        )
    )

    agent = create_agent(
        model=chat_anthropic,
        tools=build_tools(),
        system_prompt=build_system_prompt(),
        middleware=[handle_tool_errors],
        name="命令行助手",
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
        printed_count = len(input_messages)
        for chunk in agent.stream({"messages": input_messages}, stream_mode="values"):
            printed_count = _print_chunk(printed_count, chunk)
            latest_chunk = chunk
        print("\n=== 运行结束 ===")
        if latest_chunk is None:
            raise RuntimeError("智能体没有返回任何结果。")
        return latest_chunk["messages"]

    result = agent.invoke({"messages": input_messages})
    return result["messages"]


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
    parser = argparse.ArgumentParser(description="LangChain create_agent + 命令行 ReAct 智能体 Demo")
    parser.add_argument(
        "question",
        nargs="*",
        help='单次提问内容。例如：python agents/bash_assistant_re_act/main.py "查看当前项目下有哪些 Python 文件"',
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
