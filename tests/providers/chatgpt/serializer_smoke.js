const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");
const body = new FakeNode("body");
const document = { body, scrollingElement: body, querySelector: () => null, querySelectorAll: () => [], execCommand: () => false };
const { context } = loadContentRuntime({ document });
const math = { nodeType: 1, tagName: "MATH", classList: { contains: () => false }, getAttribute: () => null, childNodes: [], querySelector: () => ({ textContent: "x^2" }), matches: () => false, closest: () => null };
assert.equal(context.WebLLMBridge.serializeMessageToMarkdown(math, context.WebLLMBridge.ChatGPTSerializer), "$x^2$");
