async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }

  return response.json();
}

export function getAgents() {
  return requestJson("/api/agents");
}

export function getAgent(agentId) {
  return requestJson(`/api/agents/${encodeURIComponent(agentId)}`);
}

export function getRootEnv() {
  return requestJson("/api/env/root");
}

export function saveRootEnv(content) {
  return requestJson("/api/env/root", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export function getRootEnvExample() {
  return requestJson("/api/env/root/example");
}

export function getAgentEnv(agentId) {
  return requestJson(`/api/env/agents/${encodeURIComponent(agentId)}`);
}

export function saveAgentEnv(agentId, content) {
  return requestJson(`/api/env/agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export function getAgentEnvExample(agentId) {
  return requestJson(`/api/env/agents/${encodeURIComponent(agentId)}/example`);
}
