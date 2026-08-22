const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const SOURCE_PATH = "tools/chatgpt_web_bridge/extension/content.js";

class FakeNode {
  constructor(kind, attrs = {}, text = "") {
    this.kind = kind;
    this.attrs = { ...attrs };
    this.innerText = text;
    this.textContent = text;
    this.childNodes = [];
    this.children = [];
    this.parentElement = null;
    this.nodeType = 1;
    this.tagName = kind === "button" ? "BUTTON" : "DIV";
    this.disabled = false;
    this.isContentEditable = false;
    this.value = "";
    this.childElementCount = 0;
    this.classList = { contains: () => false };
  }

  getAttribute(name) { return this.attrs[name] ?? null; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }

  matches(selector) {
    if (selector.includes(",")) return selector.split(",").some((part) => this.matches(part.trim()));
    if (selector === "#prompt-textarea") return this.kind === "prompt";
    if (selector === "#composer-submit-button") return this.kind === "button";
    if (selector === '[data-testid="send-button"]') return this.kind === "button";
    if (selector === 'button[aria-label="Send prompt"]') return this.kind === "button";
    if (selector === '[data-testid="stop-button"]') return this.kind === "stop";
    if (selector === 'button[aria-label*="Stop"]') return this.kind === "stop";
    if (selector === '[data-message-author-role="user"]') return this.kind === "user";
    if (selector === '[data-message-author-role="assistant"]') return this.kind === "assistant";
    if (selector === '[data-message-author-role]') return this.kind === "user" || this.kind === "assistant";
    if (selector === "main" || selector === '[role="main"]') return this.kind === "main";
    if (selector.includes("data-testid*=") || selector.includes("aria-label*=")) return false;
    return false;
  }

  closest(selector) { return this.matches(selector) ? this : null; }
  getClientRects() { return [{}]; }
  dispatchEvent() {}
  focus() {}
  querySelectorAll() { return []; }
  querySelector() { return null; }
}

async function runSmoke() {
  const users = [];
  const assistants = [];
  let generating = false;
  let clicked = false;
  const progress = [];
  const prompt = new FakeNode("prompt");
  const sendButton = new FakeNode("button");
  const main = new FakeNode("main");
  const body = new FakeNode("body");
  const stopButton = new FakeNode("stop", { "data-testid": "stop-button" });

  sendButton.click = () => {
    if (clicked) return;
    clicked = true;
    setTimeout(() => {
      prompt.value = "";
      users.push(new FakeNode("user", { "data-message-author-role": "user" }, "延迟提交"));
      generating = true;
      assistants.push(new FakeNode("assistant", { "data-message-author-role": "assistant" }, "页面加载完成"));
    }, 150);
    setTimeout(() => { generating = false; }, 220);
  };

  const allNodes = () => [
    main,
    body,
    prompt,
    sendButton,
    ...(generating ? [stopButton] : []),
    ...users,
    ...assistants,
  ];
  const document = {
    body,
    scrollingElement: body,
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      if (selector === '[data-message-author-role="user"]') return users;
      if (selector === '[data-message-author-role="assistant"]') return assistants;
      return allNodes().filter((node) => node.matches(selector));
    },
    execCommand() { return false; },
  };
  const listeners = [];
  const context = {
    console,
    document,
    Node: { ELEMENT_NODE: 1 },
    performance,
    setTimeout,
    clearTimeout,
    InputEvent: class InputEvent {},
    window: {
      getComputedStyle: () => ({ display: "block", visibility: "visible" }),
      getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
    },
    MutationObserver: class { observe() {} },
    chrome: {
      runtime: {
        onMessage: { addListener: (listener) => listeners.push(listener) },
        sendMessage: (message) => { progress.push(message); return Promise.resolve(); },
      },
    },
  };
  const source = fs.readFileSync(SOURCE_PATH, "utf8")
    .replace("const SUBMIT_TIMEOUT_MS = 10_000;", "const SUBMIT_TIMEOUT_MS = 100;")
    .replace("const SUBMISSION_CONFIRMATION_TIMEOUT_MS = 60_000;", "const SUBMISSION_CONFIRMATION_TIMEOUT_MS = 500;")
    .replace("const STABLE_TIME_MS = 1_500;", "const STABLE_TIME_MS = 20;")
    .replace("const COMPLETION_CONFIRMATION_MS = 3_000;", "const COMPLETION_CONFIRMATION_MS = 40;")
    .replace("const POLL_INTERVAL_MS = 200;", "const POLL_INTERVAL_MS = 10;")
    .replace("const RESPONSE_IDLE_TIMEOUT_MS = 300_000;", "const RESPONSE_IDLE_TIMEOUT_MS = 500;")
    .replace("const BUTTON_READY_TIMEOUT_MS = 5_000;", "const BUTTON_READY_TIMEOUT_MS = 500;");
  vm.runInNewContext(source, context, { filename: SOURCE_PATH });
  const response = await new Promise((resolve) => {
    listeners[0]({ method: "chat", text: "延迟提交", request_id: "req-submit" }, {}, resolve);
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "页面加载完成");
  assert.ok(progress.some((message) => message.phase === "working"));
}

runSmoke().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
