import json
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import mysql_ops


@tool("list_databases")
def list_databases_tool() -> str:
    """列出当前 MySQL 实例中可见的业务数据库名称。"""
    return json.dumps(mysql_ops.ops.list_databases(), ensure_ascii=False, indent=2)


@tool("list_tables")
def list_tables_tool(database_name: str) -> str:
    """列出指定数据库里的表和表类型。"""
    return json.dumps(mysql_ops.ops.list_tables(database_name), ensure_ascii=False, indent=2)


# 使用pydantic提供的BaseModel、Field来描述参数，@tool()注解会识别
class _GetTableSchemaToolArgs(BaseModel):
    database_name: str = Field(..., description="数据库名称")
    table_name: str = Field(..., description="表名称")


@tool("get_table_schema", args_schema=_GetTableSchemaToolArgs)
def get_table_schema_tool(database_name: str, table_name: str) -> str:
    """查看指定表的字段结构。"""
    return json.dumps(
        mysql_ops.ops.get_table_schema(database_name, table_name),
        ensure_ascii=False,
        indent=2,
        default=str,
    )


@tool("run_sql")
def run_sql(sql: str) -> str:
    """执行一条 SQL 并返回结果。只读模式下仅允许 SELECT/WITH。"""
    return mysql_ops.ops.run_sql(sql)


def build_tools() -> list[Any]:
    return [list_databases_tool, list_tables_tool, get_table_schema_tool, run_sql]
