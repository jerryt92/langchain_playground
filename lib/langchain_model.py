import sys
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from lib.env_loader import load_env_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
env = load_env_config(PROJECT_ROOT)

# Anthropic 对话API
chat_anthropic = ChatAnthropic(
    model_name=env.get("ANTHROPIC_API_MODEL", "").strip(),
    base_url=env.get("ANTHROPIC_BASE_URL", "").strip() or None,
    api_key=SecretStr(env.get("ANTHROPIC_API_KEY", "").strip()),
    temperature=0.3,
    max_tokens_to_sample=32768,
    thinking={
        "type": "enabled",
        "budget_tokens": 1024
    },
)

# OpenAI 对话API
chat_open_ai = ChatOpenAI(
    model=env.get("OPENAI_MODEL", "gpt-4o-mini").strip(),
    base_url=env.get("OPENAI_BASE_URL", "").strip() or None,
    api_key=SecretStr(env.get("OPENAI_API_KEY", "").strip()),
    temperature=0.3,
    max_tokens=32768
)
