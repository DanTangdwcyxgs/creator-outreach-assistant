(function () {
  if (window.__creatorHubWhatsAppSyncV2) return;
  window.__creatorHubWhatsAppSyncV2 = true;

  const CONTROLS_ID = "creator-hub-wa-controls";
  const CURRENT_BUTTON_ID = "creator-hub-wa-sync";
  const ALL_BUTTON_ID = "creator-hub-wa-sync-all";
  const STOP_BUTTON_ID = "creator-hub-wa-stop";
  const PROGRESS_ID = "creator-hub-wa-progress";
  const TOAST_ID = "creator-hub-wa-toast";
  let syncAllRunning = false;
  let stopRequested = false;

  const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function currentChatName() {
    const composer = document.querySelector('#main [contenteditable="true"][aria-label]');
    const label = composer?.getAttribute("aria-label") || "";
    const quoted = label.match(/[“\"](.+?)[”\"]/);
    if (quoted) return quoted[1].trim();

    const headerText = document.querySelector("#main header")?.innerText || "";
    return headerText.split("\n").map((value) => value.trim()).find(Boolean) || "";
  }

  function currentTranscript() {
    const lines = [];
    const seen = new Set();
    document.querySelectorAll("#main [data-pre-plain-text]").forEach((node) => {
      const prefix = node.getAttribute("data-pre-plain-text") || "";
      const bodyNode = node.querySelector("span.selectable-text");
      const readable = bodyNode?.cloneNode(true);
      readable?.querySelectorAll("img[alt]").forEach((image) => image.replaceWith(image.getAttribute("alt") || ""));
      readable?.querySelectorAll("br").forEach((lineBreak) => lineBreak.replaceWith("\n"));
      const body = (readable?.textContent || "").replace(/\n{3,}/g, "\n\n").trim();
      const line = `${prefix}${body}`.trim();
      if (prefix && body && !seen.has(line)) {
        seen.add(line);
        lines.push(line);
      }
    });
    return lines.join("\n");
  }

  function chatTargets() {
    const rows = document.querySelectorAll('[role="grid"][aria-label="聊天列表"] [role="row"][data-testid^="list-item-"]');
    const targets = [];
    const seen = new Set();
    rows.forEach((row) => {
      const name = row.querySelector("[title]")?.getAttribute("title")?.trim() || "";
      const testId = row.getAttribute("data-testid") || "";
      if (name && testId) {
        const key = name.toLocaleLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          targets.push({ name, testId });
        }
      }
    });
    return targets;
  }

  function chatListScroller() {
    let node = document.querySelector('[role="grid"][aria-label="聊天列表"]');
    while (node) {
      if (node.scrollHeight > node.clientHeight + 20) return node;
      node = node.parentElement;
    }
    return null;
  }

  function targetRow(target) {
    const byTestId = document.querySelector(`[data-testid="${target.testId}"]`);
    const testIdName = byTestId?.querySelector("[title]")?.getAttribute("title")?.trim();
    if (testIdName === target.name) return byTestId;

    return Array.from(
      document.querySelectorAll('[role="grid"][aria-label="聊天列表"] [role="row"][data-testid^="list-item-"]')
    ).find((row) => row.querySelector("[title]")?.getAttribute("title")?.trim() === target.name) || null;
  }

  function sendSync(chatName, text) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "creator-hub-sync", payload: { chat_name: chatName, text } },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error("同步助手连接失败，请重新加载扩展"));
          } else if (!response?.ok) {
            reject(new Error(response?.error || "同步失败，请先启动达人沟通台"));
          } else {
            resolve(response.result);
          }
        }
      );
    });
  }

  function debuggerCommand(action, payload = {}) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "creator-hub-debugger", action, payload },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error("Chrome 同步控制连接失败"));
          } else if (!response?.ok) {
            reject(new Error(response?.error || "Chrome 同步控制失败"));
          } else {
            resolve(response);
          }
        }
      );
    });
  }

  async function waitForChat(targetName, timeout = 6500) {
    const deadline = Date.now() + timeout;
    let previousText = "";
    let stableChecks = 0;
    while (Date.now() < deadline && !stopRequested) {
      const text = currentChatName() === targetName ? currentTranscript() : "";
      if (text && text === previousText) {
        stableChecks += 1;
        if (stableChecks >= 2) return text;
      } else {
        stableChecks = 0;
        previousText = text;
      }
      await delay(220);
    }
    return previousText;
  }

  function notify(message, error = false, duration = 4500) {
    let toast = document.getElementById(TOAST_ID);
    if (!toast) {
      toast = document.createElement("div");
      toast.id = TOAST_ID;
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.background = error ? "#8a322d" : "#17201c";
    toast.classList.add("show");
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove("show"), duration);
  }

  function setProgress(message, visible = true) {
    const progress = document.getElementById(PROGRESS_ID);
    if (!progress) return;
    progress.textContent = message;
    progress.classList.toggle("show", visible);
  }

  function setControlsRunning(running) {
    syncAllRunning = running;
    const currentButton = document.getElementById(CURRENT_BUTTON_ID);
    const allButton = document.getElementById(ALL_BUTTON_ID);
    const stopButton = document.getElementById(STOP_BUTTON_ID);
    if (currentButton) currentButton.disabled = running;
    if (allButton) {
      allButton.disabled = running;
      allButton.textContent = running ? "同步中…" : "同步全部";
    }
    stopButton?.classList.toggle("show", running);
    if (stopButton && !running) {
      stopButton.disabled = false;
      stopButton.textContent = "停止";
    }
  }

  async function syncCurrent() {
    const button = document.getElementById(CURRENT_BUTTON_ID);
    const chatName = currentChatName();
    const text = currentTranscript();
    if (!chatName) {
      notify("请先打开一位达人的聊天", true);
      return;
    }
    if (!text) {
      notify("当前页面还没有加载可同步的文字消息", true);
      return;
    }
    button.disabled = true;
    button.textContent = "同步中…";
    try {
      const result = await sendSync(chatName, text);
      notify(`${result.chat_name}：新增 ${result.messages_added} 条，重复 ${result.messages_skipped} 条`);
    } catch (error) {
      notify(error.message || "同步失败", true);
    } finally {
      button.disabled = false;
      button.textContent = "同步当前";
    }
  }

  async function openTarget(target) {
    let lastError = new Error("没有加载出可同步的文字消息");
    for (let attempt = 0; attempt < 2 && !stopRequested; attempt += 1) {
      const initialRow = targetRow(target);
      if (!initialRow) throw new Error("聊天条目已经刷新，请重新开始同步");
      initialRow.scrollIntoView({ block: "center" });

      // WhatsApp 会回收长列表中的 DOM 条目，等待滚动稳定后必须重新定位。
      await delay(attempt === 0 ? 180 : 420);
      const settledRow = targetRow(target);
      const interactiveCell = settledRow?.querySelector(':scope > [role="gridcell"][tabindex="0"]');
      if (!interactiveCell) {
        lastError = new Error("没有找到聊天的可交互区域");
        continue;
      }

      const rect = interactiveCell.getBoundingClientRect();
      await debuggerCommand("click", {
        x: rect.left + Math.min(80, rect.width / 2),
        y: rect.top + rect.height / 2,
      });
      const text = await waitForChat(target.name, attempt === 0 ? 6500 : 9000);
      if (text) return text;
      lastError = new Error("没有加载出可同步的文字消息");
    }
    throw lastError;
  }

  async function restoreOriginalChat(originalName, targets, originalScrollTop) {
    const original = targets.find((target) => target.name === originalName);
    if (original) {
      const row = document.querySelector(`[data-testid="${original.testId}"]`);
      row?.scrollIntoView({ block: "center" });
      const cell = row?.querySelector(':scope > [role="gridcell"][tabindex="0"]');
      if (cell) {
        const rect = cell.getBoundingClientRect();
        await debuggerCommand("click", {
          x: rect.left + Math.min(80, rect.width / 2),
          y: rect.top + rect.height / 2,
        }).catch(() => {});
        await delay(250);
      }
    }
    const scroller = chatListScroller();
    if (scroller) scroller.scrollTop = originalScrollTop;
  }

  async function syncAll() {
    if (syncAllRunning) return;
    const targets = chatTargets();
    if (!targets.length) {
      notify("没有识别到聊天列表，请先打开 WhatsApp 对话页面", true);
      return;
    }
    const approved = window.confirm(
      `将依次打开并同步当前列表中的 ${targets.length} 个聊天。\n\n未读聊天可能会被标记为已读；不会发送任何消息。是否继续？`
    );
    if (!approved) return;

    stopRequested = false;
    const originalName = currentChatName();
    const originalScrollTop = chatListScroller()?.scrollTop || 0;
    const totals = { processed: 0, added: 0, skipped: 0, failed: 0, failures: [] };
    let debuggerAttached = false;
    setControlsRunning(true);

    try {
      setProgress("正在连接 WhatsApp 同步控制…");
      await debuggerCommand("attach");
      debuggerAttached = true;
      for (let index = 0; index < targets.length; index += 1) {
        if (stopRequested) break;
        const target = targets[index];
        setProgress(`正在同步 ${index + 1}/${targets.length}：${target.name}`);
        try {
          const text = await openTarget(target);
          if (stopRequested) break;
          const result = await sendSync(target.name, text);
          totals.added += result.messages_added || 0;
          totals.skipped += result.messages_skipped || 0;
        } catch (error) {
          totals.failed += 1;
          totals.failures.push(`${target.name}：${error.message || "读取失败"}`);
        }
        totals.processed += 1;
        await delay(320);
      }
    } catch (error) {
      totals.failed += 1;
      notify(error.message || "无法启动全部同步", true, 8000);
    } finally {
      if (debuggerAttached) {
        await restoreOriginalChat(originalName, targets, originalScrollTop);
        await debuggerCommand("detach").catch(() => {});
      }
      setControlsRunning(false);
      const stoppedText = stopRequested ? "已停止" : "全部完成";
      const summary = `${stoppedText}：处理 ${totals.processed}/${targets.length}，新增 ${totals.added} 条，重复 ${totals.skipped} 条，失败 ${totals.failed} 个`;
      setProgress(summary);
      const progress = document.getElementById(PROGRESS_ID);
      if (progress) progress.title = totals.failures.join("\n");
      notify(summary, totals.failed > 0, 8000);
      stopRequested = false;
    }
  }

  function installStyles() {
    if (document.getElementById("creator-hub-wa-style")) return;
    const style = document.createElement("style");
    style.id = "creator-hub-wa-style";
    style.textContent = `
      #${CONTROLS_ID} {
        position: fixed; right: 22px; bottom: 76px; z-index: 999999;
        display: flex; gap: 6px; padding: 5px; border-radius: 7px;
        background: #f7faf8; border: 1px solid #cbd8d2;
        box-shadow: 0 8px 22px rgba(0,0,0,.22);
      }
      #${CONTROLS_ID} button {
        min-height: 36px; padding: 0 11px; border-radius: 5px;
        font: 700 12px/1.2 "Segoe UI", "Microsoft YaHei", sans-serif;
        cursor: pointer;
      }
      #${CURRENT_BUTTON_ID}, #${ALL_BUTTON_ID} { border: 1px solid #0d684d; background: #14785a; color: white; }
      #${CURRENT_BUTTON_ID}:hover, #${ALL_BUTTON_ID}:hover { background: #0e5c45; }
      #${CONTROLS_ID} button:disabled { opacity: .65; cursor: wait; }
      #${STOP_BUTTON_ID} { display: none; border: 1px solid #b85247; background: white; color: #9a3f36; }
      #${STOP_BUTTON_ID}.show { display: block; }
      #${PROGRESS_ID} {
        position: fixed; right: 22px; bottom: 128px; z-index: 999999;
        display: none; max-width: 420px; padding: 9px 11px; border-radius: 5px;
        background: #f7faf8; border: 1px solid #cbd8d2; color: #33443d;
        box-shadow: 0 6px 18px rgba(0,0,0,.18);
        font: 12px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif;
      }
      #${PROGRESS_ID}.show { display: block; }
      #${TOAST_ID} {
        position: fixed; right: 22px; bottom: 176px; z-index: 1000000;
        max-width: 420px; padding: 11px 14px; border-radius: 5px;
        color: white; font: 13px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif;
        box-shadow: 0 8px 22px rgba(0,0,0,.22); opacity: 0;
        transform: translateY(8px); pointer-events: none; transition: .18s ease;
      }
      #${TOAST_ID}.show { opacity: 1; transform: translateY(0); }
    `;
    document.head.appendChild(style);
  }

  function installControls() {
    if (!document.body || document.getElementById(CONTROLS_ID)) return;
    installStyles();

    const controls = document.createElement("div");
    controls.id = CONTROLS_ID;

    const currentButton = document.createElement("button");
    currentButton.id = CURRENT_BUTTON_ID;
    currentButton.type = "button";
    currentButton.textContent = "同步当前";
    currentButton.title = "同步当前已加载的文字聊天";
    currentButton.addEventListener("click", syncCurrent);

    const allButton = document.createElement("button");
    allButton.id = ALL_BUTTON_ID;
    allButton.type = "button";
    allButton.textContent = "同步全部";
    allButton.title = "依次同步当前聊天列表中的全部对话";
    allButton.addEventListener("click", syncAll);

    const stopButton = document.createElement("button");
    stopButton.id = STOP_BUTTON_ID;
    stopButton.type = "button";
    stopButton.textContent = "停止";
    stopButton.addEventListener("click", () => {
      stopRequested = true;
      stopButton.disabled = true;
      stopButton.textContent = "正在停止…";
    });

    const progress = document.createElement("div");
    progress.id = PROGRESS_ID;
    controls.append(currentButton, allButton, stopButton);
    document.body.append(progress, controls);
  }

  installControls();
  new MutationObserver(installControls).observe(document.documentElement, { childList: true, subtree: true });
})();
