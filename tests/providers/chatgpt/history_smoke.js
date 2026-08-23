const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");
const make = (role, id, text) => new FakeNode(role, { "data-message-author-role": role, "data-turn-id": id }, text);
let stage = 0;
const current = () => stage === 0 ? [make("user", "u2", "当前问题"), make("assistant", "a2", "当前回答")] : stage === 1 ? [make("user", "u1", "旧问题"), make("assistant", "a1", "旧回答"), make("user", "u2", "当前问题"), make("assistant", "a2", "当前回答")] : stage === 2 ? [make("user", "next", "新会话")] : [make("user", "same-turn", "同一容器中的用户消息"), make("assistant", "same-turn", "同一容器中的助手消息")];
const body = new FakeNode("body"); body.scrollHeight = 1000; body.clientHeight = 100;
const document = { body, scrollingElement: body, querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }, querySelectorAll(selector) { const nodes = current(); if (selector === '[data-message-author-role]') return nodes; if (selector.includes('="user"')) return nodes.filter((node) => node.kind === "user"); if (selector.includes('="assistant"')) return nodes.filter((node) => node.kind === "assistant"); return []; }, execCommand: () => false };
const { context, listeners } = loadContentRuntime({ document, timingOverrides: { historyLoadTimeoutMs: 80, historyPollIntervalMs: 5 }, onScroll: (top) => { if (stage === 0 && top < 900) stage = 1; } });
const call = (message) => new Promise((resolve) => listeners[0](message, {}, resolve));
(async () => {
  context.scrollY = 900;
  const full = await call({ method: "get_messages", full: true }); assert.equal(full.ok, true); assert.equal(full.result.messages.length, 4); assert.equal(context.scrollY, 900);
  const deduped = await call({ method: "get_messages", full: true }); assert.equal(deduped.result.messages.length, 4);
  stage = 2; context.location.pathname = "/c/next"; const reset = await call({ method: "get_messages" }); assert.deepEqual(JSON.parse(JSON.stringify(reset.result.messages)), [{ role: "user", content: "新会话", artifacts: [] }]);
  stage = 3; context.location.pathname = "/c/duplicate"; const duplicate = await call({ method: "get_messages", full: true }); assert.deepEqual(JSON.parse(JSON.stringify(duplicate.result.messages)), [{ role: "user", content: "同一容器中的用户消息", artifacts: [] }, { role: "assistant", content: "同一容器中的助手消息", artifacts: [] }]);
  stage = 1; context.location.pathname = "/c/truncated"; context.scrollY = 100000; const short = await call({ method: "get_messages", full: true }); assert.equal(short.result.truncated, true);
})().catch((error) => { console.error(error); process.exitCode = 1; });
