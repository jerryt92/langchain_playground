from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

UNIX_BLOCKED_COMMAND_PATTERNS = [
    r"(^|\s)sudo(\s|$)",
    r"(^|\s)su(\s|$)",
    r"rm\s+-rf\s+/$",
    r"rm\s+-rf\s+/\s",
    r"rm\s+-rf\s+~(?:/|\s|$)",
    r"\bdd\b",
    r"\bmkfs(?:\.\w+)?\b",
    r"\bfdisk\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"curl\b[^|]*\|\s*(?:bash|sh)\b",
    r"wget\b[^|]*\|\s*(?:bash|sh)\b",
    r">\s*/(?:etc|bin|sbin|usr|System|Library|dev)\b",
    r":\(\)\s*\{\s*:\|\:&\s*;\s*\};:",
]

WINDOWS_BLOCKED_COMMAND_PATTERNS = [
    r"(^|\s)runas(\s|$)",
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bshutdown(?:\.exe)?\b",
    r"\breg(?:\.exe)?\s+delete\b",
    r"\bRemove-Item\b[^\n\r]*-(?:Recurse|r)\b[^\n\r]*-(?:Force|fo)\b",
    r"\bdel\b[^\n\r]*\s/[fqsa]+\b",
    r"\brmdir\b[^\n\r]*\s/[sq]+\b",
    r"\bInvoke-Expression\b",
    r"\biex\b",
    r"\bcurl(?:\.exe)?\b[^|]*\|\s*(?:iex|Invoke-Expression)\b",
    r"\birm\b[^|]*\|\s*(?:iex|Invoke-Expression)\b",
]


@dataclass
class ShellConfig:
    workspace_root: str
    extra_allowed_roots: list[str]
    command_timeout_seconds: int
    max_output_chars: int
    max_file_read_chars: int
    max_search_results: int
    shell_executable: Optional[str] = None
    extra_blocked_patterns: Optional[list[str]] = None
    platform_override: Optional[str] = None


class ShellOps:
    def __init__(self, config: ShellConfig):
        self.platform_name = (config.platform_override or platform.system()).strip() or platform.system()
        self.workspace_root = self._resolve_existing_directory(config.workspace_root)
        self.allowed_roots = self._build_allowed_roots(config.extra_allowed_roots)
        self.command_timeout_seconds = max(1, config.command_timeout_seconds)
        self.max_output_chars = max(1000, config.max_output_chars)
        self.max_file_read_chars = max(1000, config.max_file_read_chars)
        self.max_search_results = max(1, config.max_search_results)
        self.shell_executable = self._resolve_shell_executable(config.shell_executable)
        self.shell_arguments = self._resolve_shell_arguments(self.shell_executable)
        patterns = [
            *self._default_blocked_patterns(),
            *(config.extra_blocked_patterns or []),
        ]
        self.blocked_command_patterns = [re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns]

    def describe_policy(self) -> str:
        roots = ", ".join(str(root) for root in self.allowed_roots)
        return (
            f"当前系统视图为 {self.platform_name}，默认命令解释器为 {self.shell_executable}；"
            "允许在受控目录内执行大多数常见命令行命令；"
            f"工作目录限制在 {roots}；"
            f"单次命令超时 {self.command_timeout_seconds} 秒；"
            "会拦截提权、危险删除、磁盘格式化、注册表破坏和可疑远程脚本直执行等高风险命令。"
        )

    def _default_blocked_patterns(self) -> list[str]:
        if self._is_windows():
            return WINDOWS_BLOCKED_COMMAND_PATTERNS
        return UNIX_BLOCKED_COMMAND_PATTERNS

    def _is_windows(self) -> bool:
        return self.platform_name.lower().startswith("win")

    def _resolve_shell_executable(self, configured_shell: Optional[str]) -> str:
        if configured_shell and configured_shell.strip():
            return configured_shell.strip()
        if self._is_windows():
            return "powershell.exe"
        return "/bin/bash"

    def _resolve_shell_arguments(self, shell_executable: str) -> list[str]:
        executable_name = Path(shell_executable).name.lower()
        if executable_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return ["-NoLogo", "-NoProfile", "-Command"]
        if executable_name in {"cmd", "cmd.exe"}:
            return ["/d", "/s", "/c"]
        return ["-lc"]

    def _build_allowed_roots(self, extra_allowed_roots: list[str]) -> list[Path]:
        roots = [self.workspace_root]
        for item in extra_allowed_roots:
            roots.append(self._resolve_existing_directory(item))

        unique_roots: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            if root not in seen:
                seen.add(root)
                unique_roots.append(root)
        return unique_roots

    def _resolve_existing_directory(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"目录不存在：{path}")
        if not path.is_dir():
            raise NotADirectoryError(f"不是目录：{path}")
        return path

    def _resolve_user_path(self, raw_path: str, default_base: Optional[Path] = None) -> Path:
        text = raw_path.strip()
        if not text:
            raise ValueError("路径不能为空。")

        path = Path(text).expanduser()
        if path.is_absolute():
            resolved = path.resolve()
        else:
            base = default_base or self.workspace_root
            resolved = (base / path).resolve()
        self._ensure_allowed_path(resolved)
        return resolved

    def _ensure_allowed_path(self, path: Path) -> None:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return
            except ValueError:
                continue
        raise PermissionError(f"路径超出允许范围：{path}")

    def _normalize_working_dir(self, working_dir: Optional[str]) -> Path:
        if working_dir:
            return self._resolve_user_path(working_dir, default_base=self.workspace_root)
        return self.workspace_root

    def _truncate_text(self, text: str, limit: int) -> tuple[str, bool]:
        if len(text) <= limit:
            return text, False
        return text[:limit], True

    def _check_command_policy(self, command: str) -> None:
        normalized = command.strip()
        if not normalized:
            raise ValueError("命令不能为空。")
        for pattern in self.blocked_command_patterns:
            if pattern.search(normalized):
                raise PermissionError(f"命令被安全策略拦截：{pattern.pattern}")

    def run_command(self, command: str, working_dir: Optional[str] = None) -> dict[str, Any]:
        self._check_command_policy(command)
        resolved_working_dir = self._normalize_working_dir(working_dir)
        command_args = [self.shell_executable, *self.shell_arguments, command]

        try:
            completed = subprocess.run(
                command_args,
                cwd=str(resolved_working_dir),
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            stdout, stdout_truncated = self._truncate_text(stdout, self.max_output_chars)
            stderr, stderr_truncated = self._truncate_text(stderr, self.max_output_chars)
            return {
                "platform": self.platform_name,
                "shell": self.shell_executable,
                "command": command,
                "working_dir": str(resolved_working_dir),
                "timed_out": True,
                "timeout_seconds": self.command_timeout_seconds,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "exit_code": None,
            }

        stdout, stdout_truncated = self._truncate_text(completed.stdout, self.max_output_chars)
        stderr, stderr_truncated = self._truncate_text(completed.stderr, self.max_output_chars)
        return {
            "platform": self.platform_name,
            "shell": self.shell_executable,
            "command": command,
            "working_dir": str(resolved_working_dir),
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "exit_code": completed.returncode,
        }

    def list_dir(self, path: str = ".", limit: int = 200) -> dict[str, Any]:
        resolved = self._resolve_user_path(path, default_base=self.workspace_root)
        if not resolved.exists():
            raise FileNotFoundError(f"路径不存在：{resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"不是目录：{resolved}")

        entries = []
        sorted_entries = sorted(resolved.iterdir(), key=lambda item: item.name.lower())
        for item in sorted_entries[: max(1, limit)]:
            entry: dict[str, Any] = {
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    pass
            entries.append(entry)

        return {
            "path": str(resolved),
            "entries": entries,
            "truncated": len(sorted_entries) > max(1, limit),
            "total_entries": len(sorted_entries),
        }

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_user_path(path, default_base=self.workspace_root)
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在：{resolved}")
        if not resolved.is_file():
            raise IsADirectoryError(f"路径不是文件：{resolved}")

        content = resolved.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        line_count = len(lines)
        normalized_start = max(1, start_line)
        normalized_end = line_count if end_line is None else max(normalized_start, end_line)
        selected = lines[normalized_start - 1: normalized_end]
        numbered = [f"{index}|{line}" for index, line in enumerate(selected, start=normalized_start)]
        text = "\n".join(numbered)
        text, truncated = self._truncate_text(text, self.max_file_read_chars)

        return {
            "path": str(resolved),
            "start_line": normalized_start,
            "end_line": min(normalized_end, line_count),
            "line_count": line_count,
            "content": text,
            "truncated": truncated,
        }

    def search_files(
        self,
        pattern: str,
        path: str = ".",
        is_regex: bool = False,
    ) -> dict[str, Any]:
        if not pattern.strip():
            raise ValueError("搜索模式不能为空。")

        base_path = self._resolve_user_path(path, default_base=self.workspace_root)
        if not base_path.exists():
            raise FileNotFoundError(f"路径不存在：{base_path}")

        compiled = re.compile(pattern if is_regex else re.escape(pattern), flags=re.IGNORECASE)
        matches: list[dict[str, Any]] = []

        walker = [base_path] if base_path.is_file() else sorted(base_path.rglob("*"))
        for candidate in walker:
            if len(matches) >= self.max_search_results:
                break
            if not candidate.is_file():
                continue
            try:
                if candidate.stat().st_size > 1024 * 1024:
                    continue
                content = candidate.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for line_number, line in enumerate(content.splitlines(), start=1):
                if compiled.search(line):
                    matches.append(
                        {
                            "path": str(candidate),
                            "line_number": line_number,
                            "line": line.strip(),
                        }
                    )
                    if len(matches) >= self.max_search_results:
                        break

        return {
            "base_path": str(base_path),
            "pattern": pattern,
            "is_regex": is_regex,
            "matches": matches,
            "truncated": len(matches) >= self.max_search_results,
        }

    def run_command_json(self, command: str, working_dir: Optional[str] = None) -> str:
        return json.dumps(self.run_command(command, working_dir), ensure_ascii=False, indent=2)

    def list_dir_json(self, path: str = ".", limit: int = 200) -> str:
        return json.dumps(self.list_dir(path, limit), ensure_ascii=False, indent=2)

    def read_file_json(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        return json.dumps(
            self.read_file(path=path, start_line=start_line, end_line=end_line),
            ensure_ascii=False,
            indent=2,
        )

    def search_files_json(self, pattern: str, path: str = ".", is_regex: bool = False) -> str:
        return json.dumps(
            self.search_files(pattern=pattern, path=path, is_regex=is_regex),
            ensure_ascii=False,
            indent=2,
        )


ops: ShellOps
