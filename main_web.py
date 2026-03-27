from __future__ import annotations

import argparse
import asyncio
import json
import os
import pty
import subprocess
import sys
import termios
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lib.agent_registry import AgentInfo, discover_agents, get_agent_by_id

PROJECT_ROOT = Path(__file__).resolve().parent
AGENTS_DIR = PROJECT_ROOT / "agents"
WEB_DIR = PROJECT_ROOT / "web"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Agent Engine Web Shell")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class EnvFilePayload(BaseModel):
    content: str


def _list_agents() -> list[AgentInfo]:
    return discover_agents(AGENTS_DIR)


def _serialize_agent(agent: AgentInfo) -> dict[str, str]:
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "description": agent.description,
    }


def _require_agent(agent_id: str) -> AgentInfo:
    agent = get_agent_by_id(AGENTS_DIR, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    return agent


def _read_env_payload(path: Path) -> dict[str, str | bool]:
    if path.exists():
        content = path.read_text(encoding="utf-8")
        exists = True
    else:
        content = ""
        exists = False
    return {"content": content, "exists": exists}


def _write_env_payload(path: Path, content: str) -> dict[str, str | bool]:
    path.write_text(content, encoding="utf-8")
    return {"content": content, "exists": True}


@app.get("/", response_class=FileResponse)
async def home_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/agents", response_class=JSONResponse)
async def list_agents() -> list[dict[str, str]]:
    return [_serialize_agent(agent) for agent in _list_agents()]


@app.get("/api/agents/{agent_id}", response_class=JSONResponse)
async def get_agent(agent_id: str) -> dict[str, str]:
    agent = get_agent_by_id(AGENTS_DIR, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    return _serialize_agent(agent)


@app.get("/api/env/root", response_class=JSONResponse)
async def get_root_env() -> dict[str, str | bool]:
    return _read_env_payload(PROJECT_ROOT / ".env")


@app.put("/api/env/root", response_class=JSONResponse)
async def save_root_env(payload: EnvFilePayload) -> dict[str, str | bool]:
    return _write_env_payload(PROJECT_ROOT / ".env", payload.content)


@app.get("/api/env/agents/{agent_id}", response_class=JSONResponse)
async def get_agent_env(agent_id: str) -> dict[str, str | bool]:
    agent = _require_agent(agent_id)
    return _read_env_payload(agent.directory / ".env")


@app.put("/api/env/agents/{agent_id}", response_class=JSONResponse)
async def save_agent_env(agent_id: str, payload: EnvFilePayload) -> dict[str, str | bool]:
    agent = _require_agent(agent_id)
    return _write_env_payload(agent.directory / ".env", payload.content)


@app.get("/api/env/agents/{agent_id}/example", response_class=JSONResponse)
async def get_agent_env_example(agent_id: str) -> dict[str, str | bool]:
    agent = _require_agent(agent_id)
    return _read_env_payload(agent.directory / ".env.example")


@app.get("/api/env/root/example", response_class=JSONResponse)
async def get_root_env_example() -> dict[str, str | bool]:
    return _read_env_payload(PROJECT_ROOT / ".env.example")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/terminal/{agent_id}", response_class=FileResponse)
async def terminal_page(agent_id: str) -> FileResponse:
    _require_agent(agent_id)
    return FileResponse(WEB_DIR / "terminal.html")


@app.websocket("/ws/terminal/{agent_id}")
async def terminal_socket(websocket: WebSocket, agent_id: str) -> None:
    agent = get_agent_by_id(AGENTS_DIR, agent_id)
    if agent is None:
        await websocket.close(code=1008, reason=f"Unknown agent: {agent_id}")
        return

    await websocket.accept()
    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as exc:
        await websocket.send_text(f"\r\n[PTY 初始化失败] {exc}\r\n")
        await websocket.close(code=1011)
        return
    process: subprocess.Popen[bytes] | None = None

    try:
        process = subprocess.Popen(
            [sys.executable, str(agent.entrypoint)],
            cwd=str(PROJECT_ROOT),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            env=os.environ.copy(),
        )
        os.close(slave_fd)
        slave_fd = -1

        async def pump_pty_output() -> None:
            while True:
                chunk = await asyncio.to_thread(os.read, master_fd, 4096)
                if not chunk:
                    break
                await websocket.send_text(chunk.decode("utf-8", errors="ignore"))

        async def pump_websocket_input() -> None:
            while True:
                raw_message = await websocket.receive_text()
                payload = json.loads(raw_message)
                message_type = payload.get("type")
                if message_type == "input":
                    await asyncio.to_thread(
                        os.write,
                        master_fd,
                        payload.get("data", "").encode("utf-8"),
                    )
                elif message_type == "resize":
                    _resize_pty(
                        master_fd,
                        int(payload.get("rows", 24)),
                        int(payload.get("cols", 80)),
                    )

        output_task = asyncio.create_task(pump_pty_output())
        input_task = asyncio.create_task(pump_websocket_input())
        done, pending = await asyncio.wait(
            {output_task, input_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)


def _resize_pty(fd: int, rows: int, cols: int) -> None:
    size = termios.tcgetwinsize(fd)
    termios.tcsetwinsize(fd, (rows, cols))
    if size == (rows, cols):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent Engine Web Shell")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    # 检测调试模式
    is_debug = "pydevd" in sys.modules or "PYCHARM_HOSTED" in os.environ

    print(f"🚀 Starting Milvus Service on {args.host}:{args.port}")

    if is_debug:
        print("🔧 Debug mode detected")
        config = uvicorn.Config(app, host=args.host, port=args.port, reload=True)
        server = uvicorn.Server(config)
        import asyncio

        asyncio.run(server.serve())
    else:
        uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
