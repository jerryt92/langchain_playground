from typing import Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agents.bash_assistant_re_act import shell_ops


class _RunCommandArgs(BaseModel):
    command: str = Field(..., description="要执行的命令行命令。")
    working_dir: Optional[str] = Field(
        default=".",
        description="命令执行目录。支持相对路径；相对路径相对于工作区根目录解析。",
    )


@tool("run_command", args_schema=_RunCommandArgs)
def run_command_tool(command: str, working_dir: Optional[str] = ".") -> str:
    """在指定工作目录执行一条命令行命令，并返回 stdout/stderr/exit_code。"""
    return shell_ops.ops.run_command_json(command=command, working_dir=working_dir)


class _ListDirArgs(BaseModel):
    path: str = Field(default=".", description="要查看的目录路径。")
    limit: int = Field(default=200, ge=1, le=1000, description="最多返回多少条目录项。")


@tool("list_dir", args_schema=_ListDirArgs)
def list_dir_tool(path: str = ".", limit: int = 200) -> str:
    """列出目录中的文件和子目录。"""
    return shell_ops.ops.list_dir_json(path=path, limit=limit)


class _ReadFileArgs(BaseModel):
    path: str = Field(..., description="要读取的文件路径。")
    start_line: int = Field(default=1, ge=1, description="起始行号，1 开始。")
    end_line: Optional[int] = Field(default=None, description="结束行号，留空表示读到文件末尾。")


@tool("read_file", args_schema=_ReadFileArgs)
def read_file_tool(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
    """读取文本文件内容，并带行号返回。"""
    return shell_ops.ops.read_file_json(path=path, start_line=start_line, end_line=end_line)


class _SearchFilesArgs(BaseModel):
    pattern: str = Field(..., description="要搜索的文本或正则模式。")
    path: str = Field(default=".", description="搜索起点，可以是目录或单个文件。")
    is_regex: bool = Field(default=False, description="是否把 pattern 当作正则表达式。")


@tool("search_files", args_schema=_SearchFilesArgs)
def search_files_tool(pattern: str, path: str = ".", is_regex: bool = False) -> str:
    """在文件中搜索文本，返回匹配文件、行号和内容。"""
    return shell_ops.ops.search_files_json(pattern=pattern, path=path, is_regex=is_regex)


def build_tools() -> list[Any]:
    return [run_command_tool, list_dir_tool, read_file_tool, search_files_tool]
