const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../../..");
let closed = false;
let calls = 0;
let failAfterSend = false;
const context = { globalThis: null, URL, setTimeout, clearTimeout, chrome: { tabs: {
  get: async () => { if (closed || (failAfterSend && calls >= 2)) throw new Error("closed"); return { id: 7, url: "https://chatgpt.com/c/test" }; },
  sendMessage: async () => { calls += 1; if (calls % 2 === 1) return { ok: true, result: { ready: true } }; if (failAfterSend) return { ok: true, result: { text: "sent" } }; throw new Error("transport lost"); },
} } };
context.globalThis = context; vm.createContext(context);
for (const file of ["extension/core/utils.js", "extension/core/registry.js", "extension/core/tabs.js", "extension/providers/chatgpt/profile.js"]) vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context, { filename: file });
context.WebLLMBridge.registerProvider(context.WebLLMBridge.ChatGPTProfile);
context.WebLLMBridge.registerProvider({ id: "other", matchesUrl: (url) => String(url).includes("other.example"), normalizeUrl: (url) => url });
const tabs = context.WebLLMBridge.createTabs({ contentReadyTimeoutMs: 10, contentRetryIntervalMs: 1 });
(async () => {
  await assert.rejects(() => tabs.request("chat", { tab_id: 7, provider: "chatgpt" }), (error) => error.code === "CHAT_STATE_UNKNOWN" && error.safeToRetry === false);
  calls = 0; failAfterSend = true;
  await assert.rejects(() => tabs.request("chat", { tab_id: 7, provider: "chatgpt" }), (error) => error.code === "CHAT_STATE_UNKNOWN" && error.safeToRetry === false);
  failAfterSend = false;
  await assert.rejects(() => tabs.request("get_messages", { tab_id: 7, provider: "other" }), (error) => error.code === "INVALID_URL");
  closed = true;
  await assert.rejects(() => tabs.request("get_messages", { tab_id: 7, provider: "chatgpt" }), (error) => error.code === "TAB_CLOSED" && error.safeToRetry === true);
})().catch((error) => { console.error(error); process.exitCode = 1; });
