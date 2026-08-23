importScripts(
  "core/utils.js",
  "core/registry.js",
  "core/rpc.js",
  "core/tabs.js",
  "providers/chatgpt/profile.js",
  "providers/chatgpt/serializer.js",
  "providers/chatgpt/adapter.js",
);

const BRIDGE_URL = "ws://127.0.0.1:8765";
const PROTOCOL_VERSION = 2;
const HEARTBEAT_INTERVAL_MS = 20_000;
const RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 10_000;
const CONTENT_READY_TIMEOUT_MS = 30_000;
const CONTENT_RETRY_INTERVAL_MS = 200;
const RECONNECT_ALARM = "web-llm-bridge-reconnect";

const bridge = globalThis.WebLLMBridge;
const tabs = bridge.createTabs({
  contentReadyTimeoutMs: CONTENT_READY_TIMEOUT_MS,
  contentRetryIntervalMs: CONTENT_RETRY_INTERVAL_MS,
});
let rpc;

async function routeRequest(method, params, requestId) {
  if (method === "open") return tabs.attach(params);
  if (method === "close_tab") return tabs.close(params?.tab_id);
  if (method === "get_messages" || method === "chat" || method === "resolve_artifact" || method === "get_artifact") {
    return tabs.request(method, { ...params, request_id: requestId });
  }
  throw bridge.error("INTERNAL_ERROR", `未知 RPC 方法：${method}`);
}

async function handleRequest(request) {
  if (typeof request?.id !== "string") return;
  try {
    const result = await routeRequest(request.method, request.params || {}, request.id);
    rpc.send({ type: "response", id: request.id, ok: true, result });
  } catch (error) {
    try {
      rpc.send({
        type: "response", id: request.id, ok: false,
        error: { code: error?.code || "INTERNAL_ERROR", message: error?.message || "浏览器扩展内部错误", safe_to_retry: error?.safeToRetry === true },
      });
    } catch (_sendError) {}
  }
}

rpc = bridge.createRpcClient({
  url: BRIDGE_URL,
  protocolVersion: PROTOCOL_VERSION,
  heartbeatIntervalMs: HEARTBEAT_INTERVAL_MS,
  reconnectDelayMs: RECONNECT_DELAY_MS,
  maxReconnectDelayMs: MAX_RECONNECT_DELAY_MS,
  onRequest: handleRequest,
});

const PROGRESS_PHASES = new Set(["submitted", "thinking", "working", "tool_call", "streaming"]);
chrome.runtime.onMessage.addListener((message, sender) => {
  if (["artifact_start", "artifact_chunk", "artifact_end"].includes(message?.type)) {
    if (typeof message.request_id !== "string" || typeof message.artifact_id !== "string") return false;
    try { rpc.send({ ...message, id: message.request_id, tab_id: sender?.tab?.id, url: sender?.url || "" }); } catch (_error) {}
    return false;
  }
  if (message?.type !== "chat_progress") return false;
  const tabId = sender?.tab?.id;
  if (!Number.isInteger(tabId) || !bridge.detectProvider(sender?.url || "") || typeof message.request_id !== "string" || !PROGRESS_PHASES.has(message.phase)) return false;
  try {
    const provider = bridge.detectProvider(sender.url || "");
    rpc.send({ type: "progress", id: message.request_id, tab_id: tabId, url: sender.url || "", provider: provider.id, phase: message.phase, elapsed_ms: Number.isFinite(message.elapsed_ms) ? Math.max(0, message.elapsed_ms) : 0, idle_ms: Number.isFinite(message.idle_ms) ? Math.max(0, message.idle_ms) : 0 });
  } catch (_error) {}
  return false;
});

function ensureReconnectAlarm() { chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 0.5 }); }
chrome.runtime.onInstalled.addListener(() => { ensureReconnectAlarm(); rpc.connect(); });
chrome.runtime.onStartup.addListener(() => { ensureReconnectAlarm(); rpc.connect(); });
chrome.action.onClicked.addListener(() => rpc.connect(true));
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === RECONNECT_ALARM) rpc.connect(); });
ensureReconnectAlarm();
rpc.connect();
