const state = {
  creators: [],
  selectedId: null,
  selectedCreator: null,
  settings: null,
  importMode: "paste",
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}

function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3000);
}

function setBusy(button, busy, label) {
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.label;
}

function openDialog(id) { $(id).showModal(); }
function closeDialog(id) { $(id).close(); }

function initials(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function renderCreators() {
  const list = $("creatorList");
  list.replaceChildren();
  if (!state.creators.length) {
    const empty = document.createElement("div");
    empty.className = "sidebar-empty";
    empty.textContent = "还没有达人档案";
    list.append(empty);
    return;
  }
  state.creators.forEach((creator) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `creator-item${creator.id === state.selectedId ? " active" : ""}`;
    const avatar = document.createElement("span");
    avatar.className = "mini-avatar";
    avatar.textContent = initials(creator.name);
    const info = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = creator.name;
    const detail = document.createElement("small");
    detail.textContent = creator.product || creator.handle || creator.status;
    info.append(name, detail);
    const count = document.createElement("span");
    count.className = "creator-count";
    count.textContent = creator.message_count || "";
    button.append(avatar, info, count);
    button.addEventListener("click", () => selectCreator(creator.id));
    list.append(button);
  });
}

async function loadCreators(query = "") {
  const data = await api(`/api/creators?q=${encodeURIComponent(query)}`);
  state.creators = data.creators;
  renderCreators();
  if (!state.selectedId && !query && state.creators.length) await selectCreator(state.creators[0].id);
}

function showCreator(creator) {
  state.selectedCreator = creator;
  $("emptyState").classList.add("hidden");
  $("conversationContent").classList.remove("hidden");
  $("creatorAvatar").textContent = initials(creator.name);
  $("creatorName").textContent = creator.name;
  $("creatorStatus").textContent = creator.status;
  $("creatorMeta").textContent = [creator.handle, creator.product].filter(Boolean).join(" · ") || "尚未填写合作资料";
  $("summaryText").textContent = creator.summary || "暂无摘要";
  $("nextActionText").textContent = creator.next_action || "待分析";
  $("analyzeButton").disabled = false;
  $("generateButton").disabled = false;
  $("assistantPlaceholder").classList.remove("hidden");
  $("resultArea").classList.add("hidden");
}

function renderMessages(messages) {
  const stream = $("messageStream");
  stream.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "messages-empty";
    empty.textContent = "还没有聊天记录，点击“粘贴聊天”追加。";
    stream.append(empty);
    return;
  }
  let currentDate = "";
  messages.forEach((message) => {
    const date = String(message.sent_at).slice(0, 10);
    if (date !== currentDate) {
      currentDate = date;
      const separator = document.createElement("div");
      separator.className = "date-separator";
      separator.textContent = date;
      stream.append(separator);
    }
    const row = document.createElement("div");
    row.className = `message-row ${message.direction}`;
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    const sender = document.createElement("span");
    sender.className = "message-sender";
    sender.textContent = message.sender;
    const body = document.createElement("div");
    body.className = "message-body";
    body.textContent = message.body;
    const time = document.createElement("span");
    time.className = "message-time";
    time.textContent = formatTime(message.sent_at);
    bubble.append(sender, body, time);
    row.append(bubble);
    stream.append(row);
  });
  stream.scrollTop = stream.scrollHeight;
}

async function selectCreator(id) {
  state.selectedId = id;
  renderCreators();
  const [creator, messages] = await Promise.all([
    api(`/api/creators/${id}`),
    api(`/api/creators/${id}/messages`),
  ]);
  showCreator(creator);
  renderMessages(messages.messages);
}

function creatorPayload() {
  return {
    name: $("nameInput").value,
    handle: $("handleInput").value,
    status: $("statusInput").value,
    product: $("productInput").value,
    terms: $("termsInput").value,
    style_notes: $("styleNotesInput").value,
    notes: $("notesInput").value,
  };
}

function editCreator(creator = null) {
  $("creatorDialogTitle").textContent = creator ? "编辑达人" : "新增达人";
  $("creatorId").value = creator?.id || "";
  $("nameInput").value = creator?.name || "";
  $("handleInput").value = creator?.handle || "";
  $("statusInput").value = creator?.status || "洽谈中";
  $("productInput").value = creator?.product || "";
  $("termsInput").value = creator?.terms || "";
  $("styleNotesInput").value = creator?.style_notes || "";
  $("notesInput").value = creator?.notes || "";
  $("deleteCreatorButton").classList.toggle("hidden", !creator);
  openDialog("creatorDialog");
}

async function saveCreator(event) {
  event.preventDefault();
  const id = $("creatorId").value;
  const creator = await api(id ? `/api/creators/${id}` : "/api/creators", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(creatorPayload()),
  });
  closeDialog("creatorDialog");
  await loadCreators();
  await selectCreator(creator.id);
  toast(id ? "达人档案已更新" : "达人档案已建立");
}

async function deleteCreator() {
  if (!state.selectedId || !confirm(`确定删除“${state.selectedCreator.name}”及其全部聊天记录吗？`)) return;
  await api(`/api/creators/${state.selectedId}`, { method: "DELETE" });
  state.selectedId = null;
  state.selectedCreator = null;
  closeDialog("creatorDialog");
  $("conversationContent").classList.add("hidden");
  $("emptyState").classList.remove("hidden");
  await loadCreators();
  toast("达人档案已删除");
}

async function importChat(event) {
  event.preventDefault();
  const button = event.submitter;
  setBusy(button, true, state.importMode === "batch" ? "正在批量导入…" : "正在解析…");
  try {
    if (state.importMode === "batch") {
      const files = [...$("batchFilesInput").files];
      if (!files.length) throw new Error("请先选择聊天文件");
      if (files.reduce((sum, file) => sum + file.size, 0) > 42_000_000) {
        throw new Error("文件总量过大，请分成两次导入");
      }
      const payload = await Promise.all(files.map(async (file) => ({
        name: file.name,
        data: await fileToBase64(file),
      })));
      const result = await api("/api/import/batch", { method: "POST", body: JSON.stringify({ files: payload }) });
      await loadCreators();
      if (state.selectedId) await selectCreator(state.selectedId);
      showBatchResult(result);
      toast(`批量完成：新增 ${result.messages_added} 条，重复 ${result.messages_skipped} 条`);
    } else {
      const result = await api(`/api/creators/${state.selectedId}/import`, {
        method: "POST",
        body: JSON.stringify({ text: $("chatImportInput").value }),
      });
      closeDialog("importDialog");
      $("chatImportInput").value = "";
      await loadCreators();
      await selectCreator(state.selectedId);
      toast(`识别 ${result.parsed} 条，新增 ${result.added} 条，重复 ${result.skipped} 条`);
    }
  } finally {
    setBusy(button, false, "");
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error(`${file.name} 读取失败`));
    reader.readAsDataURL(file);
  });
}

function setImportMode(mode) {
  state.importMode = mode;
  const batch = mode === "batch";
  $("pasteImportTab").classList.toggle("active", !batch);
  $("batchImportTab").classList.toggle("active", batch);
  $("pasteImportPanel").classList.toggle("hidden", batch);
  $("batchImportPanel").classList.toggle("hidden", !batch);
  $("importSubmitButton").textContent = batch ? "开始批量导入" : "解析并追加";
  $("importSubmitButton").dataset.label = $("importSubmitButton").textContent;
}

function showSelectedFiles() {
  const files = [...$("batchFilesInput").files];
  const totalMb = files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024;
  $("selectedFiles").textContent = files.length
    ? `已选择 ${files.length} 个文件，共 ${totalMb.toFixed(1)} MB`
    : "尚未选择文件";
  $("batchImportResult").classList.add("hidden");
}

function showBatchResult(result) {
  const box = $("batchImportResult");
  box.replaceChildren();
  const summary = document.createElement("strong");
  summary.textContent = `完成：${result.imported_files} 个文件，新增 ${result.creators_created} 位达人、${result.messages_added} 条消息`;
  box.append(summary);
  result.items.filter((item) => item.status === "skipped").forEach((item) => {
    const row = document.createElement("p");
    row.textContent = `${item.file}：${item.reason}`;
    box.append(row);
  });
  box.classList.remove("hidden");
}

async function generateDraft() {
  const button = $("generateButton");
  setBusy(button, true, "正在结合当前聊天生成…");
  try {
    const tone = document.querySelector('input[name="tone"]:checked').value;
    const result = await api(`/api/creators/${state.selectedId}/draft`, {
      method: "POST",
      body: JSON.stringify({ intent: $("intentInput").value, tone }),
    });
    $("englishReply").textContent = result.english_reply;
    $("chineseTranslation").textContent = result.chinese_translation || "—";
    $("strategyText").textContent = result.strategy || "—";
    $("riskNote").textContent = result.risk_notes || "";
    $("riskNote").classList.toggle("hidden", !result.risk_notes);
    $("resultModel").textContent = result.provider ? `· ${result.provider}` : "";
    $("resultArea").classList.remove("hidden");
    $("assistantPlaceholder").classList.add("hidden");
  } finally {
    setBusy(button, false, "");
  }
}

function fillList(id, values, emptyText) {
  const list = $(id);
  list.replaceChildren();
  (values?.length ? values : [emptyText]).forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
}

async function analyzeCreator() {
  const button = $("analyzeButton");
  setBusy(button, true, "分析中…");
  try {
    const result = await api(`/api/creators/${state.selectedId}/analyze`, {
      method: "POST", body: "{}",
    });
    fillList("factsList", result.confirmed_facts, "暂无");
    fillList("questionsList", result.open_questions, "暂无");
    fillList("risksList", result.risks, "暂无");
    showCreator(result.creator);
    openDialog("analysisDialog");
    await loadCreators();
    toast(`分析完成：${result.model}`);
  } finally {
    setBusy(button, false, "");
  }
}

const providerPresets = {
  local: { base_url: "http://127.0.0.1:1234/v1", model: "gemma-4-12b" },
  gemini: { base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-3.5-flash" },
  groq: { base_url: "https://api.groq.com/openai/v1", model: "qwen/qwen3.6-27b" },
  openrouter: { base_url: "https://openrouter.ai/api/v1", model: "openrouter/free" },
};

function providerChanged(fill = true) {
  const provider = $("providerInput").value;
  if (fill && providerPresets[provider]) {
    $("baseUrlInput").value = providerPresets[provider].base_url;
    $("modelInput").value = providerPresets[provider].model;
  }
  const remote = provider !== "local";
  const privacyMessages = {
    gemini: "Gemini 免费额度的数据可能用于改进 Google 产品，并可能由人工审阅。程序会先隐藏邮箱、电话和详细地址。",
    groq: "Groq 默认不保留普通推理请求；程序仍会先隐藏邮箱、电话和详细地址。",
    openrouter: "OpenRouter 免费请求可能由不同模型服务商处理；程序会先隐藏邮箱、电话和详细地址。",
  };
  $("privacyNote").textContent = remote
    ? (privacyMessages[provider] || "网络模式会把已隐去敏感信息的聊天内容发送给模型服务商。")
    : "本机模式：聊天、档案和生成内容都留在这台电脑，不会发送到网络模型。";
  $("redactionInput").disabled = !remote;
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  $("businessNameInput").value = state.settings.business_name;
  $("providerInput").value = state.settings.provider;
  $("baseUrlInput").value = state.settings.base_url;
  $("modelInput").value = state.settings.model;
  $("apiKeyInput").value = "";
  $("redactionInput").checked = state.settings.remote_redaction;
  $("fallbackInput").checked = state.settings.fallback_local;
  providerChanged(false);
}

function settingsPayload() {
  return {
    business_name: $("businessNameInput").value,
    provider: $("providerInput").value,
    base_url: $("baseUrlInput").value,
    model: $("modelInput").value,
    api_key: $("apiKeyInput").value,
    remote_redaction: $("redactionInput").checked,
    fallback_local: $("fallbackInput").checked,
  };
}

async function saveSettings(event) {
  event.preventDefault();
  state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(settingsPayload()) });
  closeDialog("settingsDialog");
  await checkHealth();
  toast("模型设置已保存");
}

async function testProvider() {
  const button = $("testProviderButton");
  setBusy(button, true, "正在连接…");
  try {
    const result = await api("/api/settings/test", { method: "POST", body: JSON.stringify(settingsPayload()) });
    $("settingsStatus").textContent = `连接成功：${result.models.slice(0, 4).join("、") || "接口可用"}`;
  } catch (error) {
    $("settingsStatus").textContent = error.message;
    throw error;
  } finally {
    setBusy(button, false, "");
  }
}

async function checkHealth() {
  const node = $("modelState");
  try {
    const health = await api("/api/health");
    node.className = `model-state ${health.model_status === "ready" ? "ready" : "offline"}`;
    node.querySelector("span").textContent = health.model_status === "ready"
      ? `${health.provider === "local" ? "本机" : "网络"}模型已就绪`
      : "模型未连接";
  } catch {
    node.className = "model-state offline";
    node.querySelector("span").textContent = "服务未连接";
  }
}

function bindEvents() {
  $("newCreatorButton").addEventListener("click", () => editCreator());
  $("emptyNewButton").addEventListener("click", () => editCreator());
  $("profileButton").addEventListener("click", () => editCreator(state.selectedCreator));
  $("creatorForm").addEventListener("submit", saveCreator);
  $("deleteCreatorButton").addEventListener("click", deleteCreator);
  $("importButton").addEventListener("click", () => { setImportMode("paste"); openDialog("importDialog"); });
  $("importForm").addEventListener("submit", importChat);
  $("pasteImportTab").addEventListener("click", () => setImportMode("paste"));
  $("batchImportTab").addEventListener("click", () => setImportMode("batch"));
  $("batchFilesInput").addEventListener("change", showSelectedFiles);
  $("generateButton").addEventListener("click", generateDraft);
  $("analyzeButton").addEventListener("click", analyzeCreator);
  $("copyReplyButton").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("englishReply").textContent);
    toast("英文回复已复制");
  });
  $("settingsButton").addEventListener("click", async () => { await loadSettings(); openDialog("settingsDialog"); });
  $("settingsForm").addEventListener("submit", saveSettings);
  $("testProviderButton").addEventListener("click", testProvider);
  $("providerInput").addEventListener("change", () => providerChanged(true));
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  let searchTimer;
  $("creatorSearch").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadCreators(event.target.value).catch(handleError), 200);
  });
  window.addEventListener("unhandledrejection", (event) => { event.preventDefault(); handleError(event.reason); });
}

function handleError(error) {
  console.error(error);
  toast(error?.message || "操作失败", true);
}

async function init() {
  bindEvents();
  await Promise.all([checkHealth(), loadSettings()]);
  await loadCreators();
}

init().catch(handleError);
