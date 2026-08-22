(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.createRpcClient = function createRpcClient(options) {
    let socket = null; let reconnectTimer = null; let heartbeatTimer = null; let delay = options.reconnectDelayMs; let ready = false; let suppressed = false;
    function send(message) { if (socket?.readyState !== WebSocket.OPEN) throw bridge.error("EXTENSION_NOT_CONNECTED", "本地 Bridge 尚未连接"); socket.send(JSON.stringify(message)); }
    function clearReconnect() { if (reconnectTimer !== null) { root.clearTimeout(reconnectTimer); reconnectTimer = null; } } function clearHeartbeat() { if (heartbeatTimer !== null) { root.clearInterval(heartbeatTimer); heartbeatTimer = null; } }
    function schedule() { if (suppressed || reconnectTimer !== null) return; reconnectTimer = root.setTimeout(() => { reconnectTimer = null; connect(); }, delay); delay = Math.min(delay * 2, options.maxReconnectDelayMs); }
    function connect(manual = false) { if (manual) { suppressed = false; delay = options.reconnectDelayMs; } if (suppressed && !manual) return; if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return; clearReconnect(); const candidate = new WebSocket(options.url); socket = candidate; ready = false;
      candidate.addEventListener("open", () => { if (socket !== candidate) return candidate.close(); candidate.send(JSON.stringify({ type: "hello", protocol_version: options.protocolVersion })); });
      candidate.addEventListener("message", (event) => { let message; try { message = JSON.parse(event.data); } catch (_error) { return; } if (message.type === "hello_ack") { if (message.protocol_version !== options.protocolVersion) { suppressed = true; ready = false; clearHeartbeat(); candidate.close(); return; } ready = true; delay = options.reconnectDelayMs; clearHeartbeat(); heartbeatTimer = root.setInterval(() => { if (ready && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" })); }, options.heartbeatIntervalMs); return; } if (message.type === "error") { const code = message.error?.code || message.code; if (["EXTENSION_ALREADY_CONNECTED", "INCOMPATIBLE_PROTOCOL"].includes(code)) { suppressed = true; ready = false; clearHeartbeat(); clearReconnect(); candidate.close(); } return; } if (message.type === "request" && ready) void options.onRequest(message); });
      candidate.addEventListener("close", () => { if (socket !== candidate) return; socket = null; ready = false; clearHeartbeat(); if (!suppressed) schedule(); });
    }
    return { connect, send };
  };
})(globalThis);
