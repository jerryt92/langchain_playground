from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def load_env_config(project_root: Path, agent_dir: Path) -> dict[str, str]:
    root_env = {
        key: value
        for key, value in dotenv_values(project_root / ".env").items()
        if value is not None
    }
    agent_env = {
        key: value
        for key, value in dotenv_values(agent_dir / ".env").items()
        if value is not None
    }

    # Priority: process env > agent .env > project root .env
    merged = {**root_env, **agent_env, **os.environ}
    return {key: str(value) for key, value in merged.items()}
