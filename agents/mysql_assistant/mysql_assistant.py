import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from mysql_ops import MySQLOps

# 最大允许 tool-use 轮数
MAX_TOOL_ROUNDS = 12


class MySQLAssistant:
    """负责 tool-use 对话循环和上下文管理。"""

    def __init__(
            self,
            mysql_ops: MySQLOps,
            openai_model: str,
            openai_api_key: str,
            openai_base_url: Optional[str] = None,
            print_model_output: bool = False,
    ):
        self.mysql_ops = mysql_ops
        self.print_model_output = print_model_output
        self.history: list[BaseMessage] = []
        self.system_message = SystemMessage(content=self.build_system_prompt())
        self.tools = self._build_tools()
        self.tools_by_name = {tool_.name: tool_ for tool_ in self.tools}
        self.llm = ChatOpenAI(
            model=openai_model,
            api_key=SecretStr(openai_api_key) if openai_api_key else None,
            base_url=openai_base_url,
            temperature=0.3,
            max_tokens=32768,
        ).bind_tools(self.tools)

    def build_system_prompt(self) -> str:
        mode_text = (
            "当前允许写操作，但每次调用 run_sql 仍然只能执行一条 SQL。"
            if self.mysql_ops.allow_write
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
        if self.mysql_ops.connection_config.database:
            lines.append(
                f"连接串里带了默认库 `{self.mysql_ops.connection_config.database}`，但不要依赖会话默认库。"
            )
        if self.mysql_ops.include_tables:
            lines.append(
                "当前启用了 INCLUDE_TABLES 过滤，仅这些表允许访问："
                + ", ".join(self.mysql_ops.include_tables)
            )
        return "\n".join(lines)

    def _build_tools(self) -> list[Any]:
        @tool("list_databases")
        def list_databases_tool() -> str:
            """列出当前 MySQL 实例中可见的业务数据库名称。"""
            return json.dumps(self.mysql_ops.list_databases(), ensure_ascii=False, indent=2)

        @tool("list_tables")
        def list_tables_tool(database_name: str) -> str:
            """列出指定数据库里的表和表类型。"""
            return json.dumps(self.mysql_ops.list_tables(database_name), ensure_ascii=False, indent=2)

        # 使用pydantic提供的BaseModel、Field来描述参数，@tool()注解会识别
        class _GetTableSchemaToolArgs(BaseModel):
            database_name: str = Field(..., description="数据库名称")
            table_name: str = Field(..., description="表名称")

        @tool("get_table_schema", args_schema=_GetTableSchemaToolArgs)
        def get_table_schema_tool(database_name: str, table_name: str) -> str:
            """查看指定表的字段结构。"""
            return json.dumps(
                self.mysql_ops.get_table_schema(database_name, table_name),
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        @tool("run_sql")
        def run_sql(sql: str) -> str:
            """执行一条 SQL 并返回结果。只读模式下仅允许 SELECT/WITH。"""
            return self.mysql_ops.run_sql(sql)

        return [list_databases_tool, list_tables_tool, get_table_schema_tool, run_sql]

    def _invoke_tool_call(self, tool_call: dict[str, Any]) -> ToolMessage:
        tool_name = tool_call["name"]
        tool_instance = self.tools_by_name.get(tool_name)
        if tool_instance is None:
            content = json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
            return ToolMessage(content=content, tool_call_id=tool_call["id"])

        try:
            result = tool_instance.invoke(tool_call.get("args", {}))
        except Exception as exc:
            result = json.dumps({"error": str(exc)}, ensure_ascii=False)

        if self.print_model_output:
            print(f"\n=== 工具调用: {tool_name} ===")
            print(json.dumps(tool_call.get("args", {}), ensure_ascii=False, indent=2))
            print("\n=== 工具结果 ===")
            print(result)

        return ToolMessage(content=str(result), tool_call_id=tool_call["id"])

    def ask(self, question: str) -> str:
        turn_messages: list[BaseMessage] = [HumanMessage(content=question)]

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.llm.invoke([self.system_message, *self.history, *turn_messages])
            turn_messages.append(response)

            if self.print_model_output:
                text = _message_to_text(response.content)
                if text:
                    print("\n=== 模型输出 ===")
                    print(text)

            tool_calls = response.tool_calls if isinstance(response, AIMessage) else []
            if not tool_calls:
                answer = _message_to_text(response.content)
                self.history.extend(turn_messages)
                return answer or "已完成，但模型没有返回可显示内容。"

            for tool_call in tool_calls:
                turn_messages.append(self._invoke_tool_call(tool_call))

        raise RuntimeError(f"工具调用轮次超过上限（{MAX_TOOL_ROUNDS}），已中止。")

    def reset_history(self) -> None:
        self.history.clear()


# 处理的输入类型：
# 字符串 - 直接去除首尾空格后返回
# 列表 - 可能是多模态消息（文本 + 图片等），会提取其中的文本部分：
# 如果列表元素是字符串，直接添加
# 如果列表元素是字典，提取 text 字段的值
# 最后用换行符拼接所有文本片段
# 其他类型 - 转换为字符串后去除空格
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
