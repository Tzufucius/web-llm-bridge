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
let handshakeReady = false;
let reconnectSuppressed = false;

function bridgeError(code, message, safeToRetry = false) {
  const error = new Error(message);
  error.code = code;
  error.safeToRetry = safeToRetry;
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
    if (handshakeReady && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "ping" }));
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function scheduleReconnect() {
  if (reconnectSuppressed || reconnectTimer !== null) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectBridge();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
}

function connectBridge(manual = false) {
  if (manual) {
    reconnectSuppressed = false;
    reconnectDelay = RECONNECT_DELAY_MS;
  }
  if (reconnectSuppressed && !manual) {
    return;
  }
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
  handshakeReady = false;

  candidate.addEventListener("open", () => {
    if (socket !== candidate) {
      candidate.close();
      return;
    }
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

    if (message.type === "hello_ack") {
      if (message.protocol_version !== PROTOCOL_VERSION) {
        reconnectSuppressed = true;
        handshakeReady = false;
        clearHeartbeatTimer();
        candidate.close();
        return;
      }
      handshakeReady = true;
      reconnectDelay = RECONNECT_DELAY_MS;
      startHeartbeat();
      return;
    }

    if (message.type === "error") {
      const errorCode = message.error?.code || message.code;
      if (
        errorCode === "EXTENSION_ALREADY_CONNECTED" ||
        errorCode === "INCOMPATIBLE_PROTOCOL"
      ) {
        reconnectSuppressed = true;
        handshakeReady = false;
        clearHeartbeatTimer();
        clearReconnectTimer();
        candidate.close();
      }
      return;
    }

    if (message.type === "request" && handshakeReady) {
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
    handshakeReady = false;
    clearHeartbeatTimer();
    if (!reconnectSuppressed) {
      scheduleReconnect();
    }
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
    throw bridgeError("TAB_CLOSED", "绑定的 ChatGPT 标签页不存在", true);
  }
  try {
    return await chrome.tabs.get(tabId);
  } catch (_error) {
    throw bridgeError("TAB_CLOSED", "绑定的 ChatGPT 标签页已关闭", true);
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
  const result = await sendToContent(tabId, {
    method,
    text: params?.text,
    limit: params?.limit,
    full: params?.full === true,
    request_id: params?.request_id,
  });
  const currentTab = await getTab(tabId);
  return { ...result, url: currentTab.url || "" };
}

async function routeRequest(method, params, requestId) {
  if (method === "open") {
    return openChatGPT(params);
  }
  if (method === "get_messages" || method === "chat") {
    return tabRequest(method, { ...params, request_id: requestId });
  }
  throw bridgeError("INTERNAL_ERROR", `未知 RPC 方法：${method}`);
}

async function handleRequest(request) {
  const requestId = request?.id;
  if (typeof requestId !== "string") {
    return;
  }

  try {
    const result = await routeRequest(
      request.method,
      request.params || {},
      requestId,
    );
    sendJson({ type: "response", id: requestId, ok: true, result });
  } catch (error) {
    const code = error?.code || "INTERNAL_ERROR";
    const message = error?.message || "浏览器扩展内部错误";
    try {
      sendJson({
        type: "response",
        id: requestId,
        ok: false,
        error: {
          code,
          message,
          safe_to_retry: error?.safeToRetry === true,
        },
      });
    } catch (_sendError) {
      // Python 可能已经断开，下一次连接会重新发送 hello。
    }
  }
}

const PROGRESS_PHASES = new Set([
  "submitted",
  "thinking",
  "working",
  "tool_call",
  "streaming",
]);

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "chat_progress") {
    return false;
  }
  const tabId = sender?.tab?.id;
  if (
    !Number.isInteger(tabId) ||
    !isChatGPTUrl(sender?.url || "") ||
    typeof message.request_id !== "string" ||
    !PROGRESS_PHASES.has(message.phase)
  ) {
    return false;
  }
  try {
    sendJson({
      type: "progress",
      id: message.request_id,
      tab_id: tabId,
      phase: message.phase,
      elapsed_ms: Number.isFinite(message.elapsed_ms)
        ? Math.max(0, message.elapsed_ms)
        : 0,
      idle_ms: Number.isFinite(message.idle_ms)
        ? Math.max(0, message.idle_ms)
        : 0,
    });
  } catch (_error) {
    // The Python Bridge may be between reconnects; final RPC handling is
    // independent from best-effort progress delivery.
  }
  return false;
});

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
  connectBridge(true);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) {
    connectBridge();
  }
});

ensureReconnectAlarm();
connectBridge();
