import { getAgents, getRootEnv, getRootEnvExample, saveRootEnv } from "./api.js";
import { createEnvEditor } from "./env-editor.js";

function renderAgents(container, agents) {
  container.innerHTML = "";
  if (!agents.length) {
    container.innerHTML = '<div class="empty-state">没有发现可运行的 agent。</div>';
    return;
  }

  for (const agent of agents) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "agent-card";
    card.innerHTML = `
      <span class="agent-chip">${agent.agent_id}</span>
      <h3>${agent.name}</h3>
      <p>${agent.description || "暂无描述"}</p>
    `;
    card.addEventListener("click", () => {
      window.location.href = `/terminal/${encodeURIComponent(agent.agent_id)}`;
    });
    container.appendChild(card);
  }
}

async function init() {
  const editor = createEnvEditor({
    textarea: document.getElementById("root-env-editor"),
    refreshButton: document.getElementById("root-env-refresh"),
    saveButton: document.getElementById("root-env-save"),
    statusElement: document.getElementById("root-env-status"),
    load: getRootEnv,
    save: saveRootEnv,
  });
  const exampleStatus = document.getElementById("root-env-example-status");
  const exampleEditor = document.getElementById("root-env-example-editor");
  const exampleRefreshButton = document.getElementById("root-env-example-refresh");

  async function refreshExample() {
    exampleStatus.textContent = "正在刷新...";
    exampleStatus.className = "status-text";
    try {
      const payload = await getRootEnvExample();
      exampleEditor.value = payload.content || "";
      exampleStatus.textContent = payload.exists ? "已加载模板文件内容。" : "模板文件不存在。";
      exampleStatus.className = "status-text success";
    } catch (error) {
      exampleStatus.textContent = `刷新失败：${error.message}`;
      exampleStatus.className = "status-text error";
    }
  }
  exampleRefreshButton.addEventListener("click", refreshExample);

  const container = document.getElementById("agents");
  try {
    const agents = await getAgents();
    renderAgents(container, agents);
  } catch (error) {
    container.innerHTML = `<div class="empty-state">加载失败：${error.message}</div>`;
  }

  await editor.refresh();
  await refreshExample();
}

init();
