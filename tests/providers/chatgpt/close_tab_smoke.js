const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../../..");
const removed = [];
const context = { globalThis: null, URL, setTimeout, clearTimeout, chrome: { tabs: {
  get: async (id) => ({ id, url: "https://chatgpt.com/c/test" }),
  remove: async (id) => { removed.push(id); },
} } };
context.globalThis = context;
vm.createContext(context);
for (const file of ["extension/core/utils.js", "extension/core/registry.js", "extension/core/tabs.js", "extension/providers/chatgpt/profile.js"]) vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context, { filename: file });
context.WebLLMBridge.registerProvider(context.WebLLMBridge.ChatGPTProfile);
const tabs = context.WebLLMBridge.createTabs({ contentReadyTimeoutMs: 10, contentRetryIntervalMs: 1 });
(async () => {
  const result = await tabs.close(17);
  assert.equal(result.tab_id, 17);
  assert.equal(result.closed, true);
  assert.deepEqual(removed, [17]);
})().catch((error) => { console.error(error); process.exitCode = 1; });
