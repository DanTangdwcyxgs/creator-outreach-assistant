const DEBUG_PROTOCOL_VERSION = "1.3";
const attachedTabs = new Set();

function whatsappTabId(sender) {
  const tabId = sender.tab?.id;
  const url = sender.tab?.url || "";
  if (!Number.isInteger(tabId) || !url.startsWith("https://web.whatsapp.com/")) {
    throw new Error("调试控制只允许用于当前 WhatsApp 网页标签");
  }
  return tabId;
}

async function attachDebugger(sender) {
  const tabId = whatsappTabId(sender);
  if (!attachedTabs.has(tabId)) {
    await chrome.debugger.attach({ tabId }, DEBUG_PROTOCOL_VERSION);
    attachedTabs.add(tabId);
  }
  return tabId;
}

async function detachDebugger(sender) {
  const tabId = whatsappTabId(sender);
  if (attachedTabs.has(tabId)) {
    try {
      await chrome.debugger.detach({ tabId });
    } finally {
      attachedTabs.delete(tabId);
    }
  }
}

async function trustedClick(sender, payload) {
  const tabId = whatsappTabId(sender);
  if (!attachedTabs.has(tabId)) throw new Error("同步控制尚未连接");
  const x = Number(payload?.x);
  const y = Number(payload?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0) {
    throw new Error("聊天点击位置无效");
  }
  const target = { tabId };
  await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
    type: "mouseMoved", x, y,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
    type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1,
  });
}

async function syncToCreatorHub(payload) {
  const response = await fetch("http://127.0.0.1:8765/api/import/whatsapp-visible", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `同步失败 (${response.status})`);
  return result;
}

async function handleMessage(message, sender) {
  if (message?.type === "creator-hub-sync") {
    whatsappTabId(sender);
    return { ok: true, result: await syncToCreatorHub(message.payload) };
  }
  if (message?.type === "creator-hub-debugger") {
    if (message.action === "attach") await attachDebugger(sender);
    else if (message.action === "click") await trustedClick(sender, message.payload);
    else if (message.action === "detach") await detachDebugger(sender);
    else throw new Error("不支持的同步控制操作");
    return { ok: true };
  }
  throw new Error("不支持的扩展消息");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!["creator-hub-sync", "creator-hub-debugger"].includes(message?.type)) return false;
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: error.message || "同步失败" }));
  return true;
});

chrome.debugger.onDetach.addListener((source) => {
  if (Number.isInteger(source.tabId)) attachedTabs.delete(source.tabId);
});

chrome.runtime.onSuspend.addListener(() => {
  attachedTabs.forEach((tabId) => chrome.debugger.detach({ tabId }).catch(() => {}));
  attachedTabs.clear();
});
