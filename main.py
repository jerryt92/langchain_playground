from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lib.agent_registry import AgentInfo, discover_agents


PROJECT_ROOT = Path(__file__).resolve().parent
AGENTS_DIR = PROJECT_ROOT / "agents"


def choose_agent(agents: list[AgentInfo]) -> AgentInfo | None:
    print("已注册的 agents：")
    for index, agent in enumerate(agents, start=1):
        description_suffix = f" - {agent.description}" if agent.description else ""
        print(f"{index}. {agent.name} ({agent.agent_id}){description_suffix}")

    while True:
        choice = input("\n请选择要运行的 agent（输入编号，q 退出）> ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            return None
        if not choice.isdigit():
            print("输入无效，请输入列表中的编号。")
            continue

        selected_index = int(choice)
        if 1 <= selected_index <= len(agents):
            return agents[selected_index - 1]

        print("编号超出范围，请重新选择。")


def run_agent(agent: AgentInfo) -> int:
    print(f"\n启动 agent: {agent.name}", flush=True)
    print("正在初始化，请稍候...\n", flush=True)
    return subprocess.run(
        [sys.executable, str(agent.entrypoint)],
        cwd=str(PROJECT_ROOT),
        check=False,
    ).returncode


def main() -> int:
    agents = discover_agents(AGENTS_DIR)
    if not agents:
        print("未发现可运行的 agent。请确保目录结构为 agents/<name>/main.py，并补充 info.json。", file=sys.stderr)
        return 1

    selected_agent = choose_agent(agents)
    if selected_agent is None:
        print("已取消。")
        return 0

    return run_agent(selected_agent)


if __name__ == "__main__":
    raise SystemExit(main())
