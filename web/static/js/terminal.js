import { getAgent, getAgentEnv, getAgentEnvExample, saveAgentEnv } from "./api.js";
import { createEnvEditor } from "./env-editor.js";

function getAgentIdFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts.at(-1) || "";
}

function buildTerminalTheme() {
  return {
    background: "#0f172a",
    foreground: "#e5eefc",
    cursor: "#93c5fd",
    cursorAccent: "#0f172a",
    selectionBackground: "rgba(96, 165, 250, 0.28)",
    black: "#1e293b",
    red: "#ef4444",
    green: "#22c55e",
    yellow: "#eab308",
    blue: "#60a5fa",
    magenta: "#c084fc",
    cyan: "#22d3ee",
    white: "#e2e8f0",
    brightBlack: "#475569",
    brightRed: "#f87171",
    brightGreen: "#4ade80",
    brightYellow: "#facc15",
    brightBlue: "#93c5fd",
    brightMagenta: "#d8b4fe",
    brightCyan: "#67e8f9",
    brightWhite: "#f8fafc",
  };
}

async function init() {
  const agentId = getAgentIdFromPath();
  const [agent] = await Promise.all([
    getAgent(agentId),
  ]);

  document.title = `${agent.name} (${agent.agent_id})`;
  document.getElementById("agent-title").textContent = `${agent.name} (${agent.agent_id})`;
  document.getElementById("agent-description").textContent =
    agent.description || "终端已连接到该 agent 的 main.py 入口。";
  document.getElementById("agent-env-title").textContent = `${agent.name} .env`;

  const editor = createEnvEditor({
    textarea: document.getElementById("agent-env-editor"),
    refreshButton: document.getElementById("agent-env-refresh"),
    saveButton: document.getElementById("agent-env-save"),
    statusElement: document.getElementById("agent-env-status"),
    load: () => getAgentEnv(agentId),
    save: (content) => saveAgentEnv(agentId, content),
  });
  await editor.refresh();

  const exampleTextarea = document.getElementById("env-example-editor");
  const exampleStatus = document.getElementById("env-example-status");
  const exampleDetails = document.getElementById("env-example-details");
  try {
    const payload = await getAgentEnvExample(agentId);
    if (payload.exists && payload.content) {
      exampleTextarea.value = payload.content;
      exampleStatus.textContent = "";
    } else {
      exampleTextarea.value = "";
      exampleStatus.textContent = "该 agent 没有 .env.example 文件。";
      exampleStatus.className = "status-text";
      exampleDetails.hidden = true;
    }
  } catch {
    exampleDetails.hidden = true;
  }

  const terminal = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontSize: 14,
    theme: buildTerminalTheme(),
  });
  const fitAddon = new FitAddon.FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(document.getElementById("terminal-host"));
  fitAddon.fit();

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/terminal/${encodeURIComponent(agentId)}`);

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({
      type: "resize",
      cols: terminal.cols,
      rows: terminal.rows,
    }));
    terminal.focus();
  });

  socket.addEventListener("message", (event) => {
    terminal.write(event.data);
  });

  socket.addEventListener("close", () => {
    terminal.write("\r\n\r\n[连接已关闭]\r\n");
  });

  socket.addEventListener("error", () => {
    terminal.write("\r\n\r\n[连接发生错误]\r\n");
  });

  terminal.onData((data) => {
    socket.send(JSON.stringify({ type: "input", data }));
  });

  window.addEventListener("resize", () => {
    fitAddon.fit();
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: "resize",
        cols: terminal.cols,
        rows: terminal.rows,
      }));
    }
  });
}

init().catch((error) => {
  document.getElementById("agent-description").textContent = `加载失败：${error.message}`;
});
