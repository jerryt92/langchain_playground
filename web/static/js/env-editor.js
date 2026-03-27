function setStatus(element, message, tone = "info") {
  element.textContent = message;
  element.className = `status-text${tone ? ` ${tone}` : ""}`;
}

export function createEnvEditor({ textarea, refreshButton, saveButton, statusElement, load, save }) {
  async function refresh() {
    setStatus(statusElement, "正在刷新...");
    try {
      const payload = await load();
      textarea.value = payload.content || "";
      setStatus(
        statusElement,
        payload.exists ? "已加载当前文件内容。" : "文件不存在，已打开空白编辑器。",
        "success",
      );
    } catch (error) {
      setStatus(statusElement, `刷新失败：${error.message}`, "error");
    }
  }

  async function persist() {
    setStatus(statusElement, "正在保存...");
    try {
      await save(textarea.value);
      setStatus(statusElement, "保存成功。", "success");
    } catch (error) {
      setStatus(statusElement, `保存失败：${error.message}`, "error");
    }
  }

  refreshButton.addEventListener("click", refresh);
  saveButton.addEventListener("click", persist);

  return {
    refresh,
    save: persist,
  };
}
