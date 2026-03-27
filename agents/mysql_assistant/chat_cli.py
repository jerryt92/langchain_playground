import argparse
import sys
import traceback
from pathlib import Path
from typing import Optional

from agents.mysql_assistant.mysql_ops import MySQLConnectionConfig, MySQLOps
from lib.agent_runtime import InteractiveAgentRuntime
from lib.langchain_model import chat_open_ai

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.env_loader import load_env_config
from mysql_assistant import MySQLAssistant
import mysql_ops
from tools import build_tools

AGENT_DIR = Path(__file__).resolve().parent


def _parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def build_assistant() -> MySQLAssistant:
    env = load_env_config(PROJECT_ROOT, AGENT_DIR)
    allow_write = _parse_bool(env.get("ALLOW_WRITE"), default=False)
    include_tables = _parse_csv(env.get("INCLUDE_TABLES"))
    print_model_output = _parse_bool(env.get("PRINT_MODEL_OUTPUT"), default=False)
    # charset = _get_first_query_value(query_params, "charset") or "utf8mb4"
    # connect_timeout = int(_get_first_query_value(query_params, "connect_timeout") or 10)
    # read_timeout = _parse_optional_int(_get_first_query_value(query_params, "read_timeout"))
    # write_timeout = _parse_optional_int(_get_first_query_value(query_params, "write_timeout"))
    mysql_connection_config = MySQLConnectionConfig(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", None),
        charset=env.get("MYSQL_CHARSET", "utf8mb4"),
        connect_timeout=int(env.get("MYSQL_CONNECT_TIMEOUT", "30")),
        read_timeout=int(env.get("MYSQL_READ_TIMEOUT", "30")),
        write_timeout=int(env.get("MYSQL_WRITE_TIMEOUT", "30"))
    )
    mysql_ops.ops = MySQLOps(
        mysql_connection_config=mysql_connection_config,
        allow_write=allow_write,
        include_tables=include_tables,
    )
    return MySQLAssistant(
        tools=build_tools(),
        llm_chat=chat_open_ai,
        print_model_output=print_model_output
    )


class MySQLAssistantRuntime(InteractiveAgentRuntime):
    def __init__(self, assistant: MySQLAssistant):
        self.assistant = assistant

    def send_message(self, message: str) -> str:
        return self.assistant.ask(message)

    def reset(self) -> None:
        self.assistant.reset_history()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangChain + MySQL 工具调用式智能体 Demo")
    parser.add_argument(
        "question",
        nargs="*",
        help='单次提问内容。例如：python agents/mysql_assistant/main.py "统计每个库的表数量"',
    )
    return parser.parse_args()


def init() -> MySQLAssistant | None:
    try:
        return build_assistant()
    except Exception as exc:
        print(f"[初始化失败] {exc}", file=sys.stderr)
        return None


def main() -> int | None:
    my_sql_assistant = init()
    if not my_sql_assistant:
        return 1

    runtime = MySQLAssistantRuntime(my_sql_assistant)
    args = parse_args()
    one_shot_question = " ".join(args.question).strip()
    if one_shot_question:
        try:
            return runtime.run_one_shot(one_shot_question)
        except Exception as exc:
            traceback.TracebackException.from_exception(exc).print()
            return 1

    try:
        return runtime.run_interactive()
    except Exception as exc:
        traceback.TracebackException.from_exception(exc).print()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
