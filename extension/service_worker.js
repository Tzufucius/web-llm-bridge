const BRIDGE_URL = "ws://127.0.0.1:8765";
const PROTOCOL_VERSION = 1;
const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 10_000;
const CONTENT_READY_TIMEOUT_MS = 30_000;
const CONTENT_RETRY_INTERVAL_MS = 200;
const RECONNECT_ALARM = "chatgpt-web-bridge-reconnect";

let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let reconnectDelay = RECONNECT_DELAY_MS;

function bridgeError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function sendJson(message) {
  if (socket?.readyState !== WebSocket.OPEN) {
    throw bridgeError("EXTENSION_NOT_CONNECTED", "Python Bridge 尚未连接");
  }
  socket.send(JSON.stringify(message));
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function clearHeartbeatTimer() {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function startHeartbeat() {
  clearHeartbeatTimer();
  heartbeatTimer = setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "ping" }));
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function scheduleReconnect() {
  if (reconnectTimer !== null) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectBridge();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
}

function connectBridge() {
  if (
    socket &&
    (socket.readyState === WebSocket.CONNECTING ||
      socket.readyState === WebSocket.OPEN)
  ) {
    return;
  }

  clearReconnectTimer();
  const candidate = new WebSocket(BRIDGE_URL);
  socket = candidate;

  candidate.addEventListener("open", () => {
    if (socket !== candidate) {
      candidate.close();
      return;
    }
    reconnectDelay = RECONNECT_DELAY_MS;
    startHeartbeat();
    candidate.send(
      JSON.stringify({
        type: "hello",
        protocol_version: PROTOCOL_VERSION,
      }),
    );
  });

  candidate.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      return;
    }

    if (message.type === "request") {
      void handleRequest(message);
    }
  });

  candidate.addEventListener("error", () => {
    // onclose will perform the reconnect with backoff.
  });

  candidate.addEventListener("close", () => {
    if (socket !== candidate) {
      return;
    }
    socket = null;
    clearHeartbeatTimer();
    scheduleReconnect();
  });
}

async function sleep(milliseconds) {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function isChatGPTUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.protocol === "https:" &&
      (parsed.hostname === "chatgpt.com" || parsed.hostname === "www.chatgpt.com")
    );
  } catch (_error) {
    return false;
  }
}

async function getTab(tabId) {
  if (!Number.isInteger(tabId)) {
    throw bridgeError("TAB_CLOSED", "绑定的 ChatGPT 标签页不存在");
  }
  try {
    return await chrome.tabs.get(tabId);
  } catch (_error) {
    throw bridgeError("TAB_CLOSED", "绑定的 ChatGPT 标签页已关闭");
  }
}

async function waitForContentScript(tabId) {
  const deadline = Date.now() + CONTENT_READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await getTab(tabId);
    try {
      const response = await chrome.tabs.sendMessage(tabId, { method: "ping" });
      if (response?.ok === true && response.result?.ready === true) {
        return;
      }
    } catch (_error) {
      // document_idle 尚未注入时，sendMessage 会失败；继续短暂重试。
    }
    await sleep(CONTENT_RETRY_INTERVAL_MS);
  }
  throw bridgeError("PAGE_NOT_READY", "ChatGPT 内容脚本在限定时间内未就绪");
}

async function sendToContent(tabId, message) {
  await getTab(tabId);
  try {
    const response = await chrome.tabs.sendMessage(tabId, message);
    if (!response || response.ok !== true) {
      const error = response?.error || {};
      throw bridgeError(
        error.code || "CONTENT_SCRIPT_UNAVAILABLE",
        error.message || "ChatGPT 内容脚本返回了无效响应",
      );
    }
    return response.result || {};
  } catch (error) {
    if (error?.code) {
      throw error;
    }
    throw bridgeError(
      "CONTENT_SCRIPT_UNAVAILABLE",
      "无法向 ChatGPT 内容脚本发送消息",
    );
  }
}

async function openChatGPT(params) {
  const url = params?.url;
  if (typeof url !== "string" || !isChatGPTUrl(url)) {
    throw bridgeError(
      "INVALID_URL",
      "仅支持 https://chatgpt.com 或 https://www.chatgpt.com",
    );
  }

  const tab = await chrome.tabs.create({ url, active: true });
  if (!tab.id) {
    throw bridgeError("PAGE_NOT_READY", "无法创建 ChatGPT 标签页");
  }
  await waitForContentScript(tab.id);
  const currentTab = await getTab(tab.id);
  return { tab_id: tab.id, url: currentTab.url || url };
}

async function tabRequest(method, params) {
  const tabId = params?.tab_id;
  await waitForContentScript(tabId);
  const result = await sendToContent(tabId, { method, text: params?.text });
  const currentTab = await getTab(tabId);
  return { ...result, url: currentTab.url || "" };
}

async function routeRequest(method, params) {
  if (method === "open") {
    return openChatGPT(params);
  }
  if (method === "get_messages" || method === "chat") {
    return tabRequest(method, params);
  }
  throw bridgeError("INTERNAL_ERROR", `未知 RPC 方法：${method}`);
}

async function handleRequest(request) {
  const requestId = request?.id;
  if (typeof requestId !== "string") {
    return;
  }

  try {
    const result = await routeRequest(request.method, request.params || {});
    sendJson({ type: "response", id: requestId, ok: true, result });
  } catch (error) {
    const code = error?.code || "INTERNAL_ERROR";
    const message = error?.message || "浏览器扩展内部错误";
    try {
      sendJson({
        type: "response",
        id: requestId,
        ok: false,
        error: { code, message },
      });
    } catch (_sendError) {
      // Python 可能已经断开，下一次连接会重新发送 hello。
    }
  }
}

function ensureReconnectAlarm() {
  chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 0.5 });
}

chrome.runtime.onInstalled.addListener(() => {
  ensureReconnectAlarm();
  connectBridge();
});

chrome.runtime.onStartup.addListener(() => {
  ensureReconnectAlarm();
  connectBridge();
});

chrome.action.onClicked.addListener(() => {
  connectBridge();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) {
    connectBridge();
  }
});

ensureReconnectAlarm();
connectBridge();
