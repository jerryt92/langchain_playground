from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentInfo:
    agent_id: str
    name: str
    description: str
    directory: Path
    entrypoint: Path
    metadata_path: Path | None


def discover_agents(agents_dir: Path) -> list[AgentInfo]:
    if not agents_dir.exists():
        return []

    agents: list[AgentInfo] = []
    seen_agent_ids: set[str] = set()
    for child in sorted(agents_dir.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue

        agent_info = load_agent_info(child)
        if agent_info is None:
            continue
        if agent_info.agent_id in seen_agent_ids:
            raise ValueError(f"发现重复的 agent_id: {agent_info.agent_id}")
        seen_agent_ids.add(agent_info.agent_id)
        agents.append(agent_info)

    return agents


def get_agent_by_id(agents_dir: Path, agent_id: str) -> AgentInfo | None:
    for agent in discover_agents(agents_dir):
        if agent.agent_id == agent_id:
            return agent
    return None


def load_agent_info(agent_dir: Path) -> AgentInfo | None:
    entrypoint = agent_dir / "main.py"
    if not entrypoint.is_file():
        return None

    metadata_path = agent_dir / "info.json"
    raw_metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        raw_metadata = _read_metadata(metadata_path)

    agent_id = _read_string(raw_metadata, "agent_id", default=agent_dir.name)
    name = _read_string(raw_metadata, "name", default=agent_dir.name)
    description = _read_string(raw_metadata, "description", default="")

    return AgentInfo(
        agent_id=agent_id,
        name=name,
        description=description,
        directory=agent_dir,
        entrypoint=entrypoint,
        metadata_path=metadata_path if metadata_path.is_file() else None,
    )


def _read_metadata(metadata_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{metadata_path} 不是有效的 JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{metadata_path} 顶层必须是 JSON 对象。")
    return data


def _read_string(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"字段 {key!r} 必须是字符串。")

    normalized = value.strip()
    if normalized:
        return normalized
    if default:
        return default
    return ""
