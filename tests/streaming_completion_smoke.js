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
    if (selector.includes(",")) {
      return selector.split(",").some((part) => this.matches(part.trim()));
    }
    if (selector === "#prompt-textarea") return this.kind === "prompt";
    if (selector === "#composer-submit-button") return this.kind === "button";
    if (selector === '[data-testid="send-button"]') return this.kind === "button";
    if (selector === 'button[aria-label="Send prompt"]') return this.kind === "button";
    if (selector === '[data-testid="stop-button"]') return this.kind === "stop";
    if (selector === 'button[aria-label*="Stop"]') return this.kind === "stop";
    if (selector === "main" || selector === '[role="main"]') return this.kind === "main";
    if (selector === '[data-message-author-role]') return Boolean(this.attrs["data-message-author-role"]);
    if (selector.includes('data-message-author-role="user"')) return this.kind === "user";
    if (selector.includes('data-message-author-role="assistant"')) return this.kind === "assistant";
    if (selector.includes('data-testid*="')) {
      const token = selector.match(/data-testid\*="([^"]+)/)?.[1];
      return Boolean(token && String(this.attrs["data-testid"] || "").includes(token));
    }
    if (selector.includes("aria-label*=")) {
      const token = selector.match(/aria-label\*="([^"]+)/)?.[1];
      return Boolean(token && String(this.attrs["aria-label"] || "").toLowerCase().includes(token.toLowerCase()));
    }
    if (selector === "[aria-live]") return this.attrs["aria-live"] != null;
    if (selector === '[role="status"]') return this.attrs.role === "status";
    if (selector === '[role="log"]') return this.attrs.role === "log";
    if (selector === '[aria-busy="true"]') return this.attrs["aria-busy"] === "true";
    if (selector.includes("[data-status]")) return this.attrs["data-status"] != null;
    return false;
  }

  closest(selector) {
    if (this.matches(selector)) return this;
    return this.parentElement ? this.parentElement.closest(selector) : null;
  }

  getClientRects() { return [{}]; }
  dispatchEvent() {}
  focus() {}

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    if (this.kind === "assistant" && this.marker && this.marker.matches(selector)) {
      return [this.marker];
    }
    return [];
  }
}

async function runScenario({ finalDelay, replaceAssistant = false, markerDelay = null, expectText }) {
  const users = [];
  const assistants = [];
  let marker = null;
  let generating = false;
  let submitted = false;
  const progress = [];
  const prompt = new FakeNode("prompt");
  const sendButton = new FakeNode("button");
  const main = new FakeNode("main");
  const body = new FakeNode("body");
  const stopButton = new FakeNode("stop", { "data-testid": "stop-button" });

  const allNodes = () => [
    main, body, prompt, sendButton,
    ...(generating ? [stopButton] : []),
    ...users,
    ...assistants,
    ...(marker ? [marker] : []),
  ];

  sendButton.click = () => {
    if (submitted) return;
    submitted = true;
    generating = true;
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "问题"));
    const first = new FakeNode("assistant", { "data-message-author-role": "assistant" }, "这是一个");
    assistants.push(first);
    setTimeout(() => { generating = false; }, 50);
    setTimeout(() => {
      const final = new FakeNode("assistant", { "data-message-author-role": "assistant" }, "这是一个完整项目");
      if (replaceAssistant) assistants.splice(0, 1, final);
      else {
        first.innerText = final.innerText;
        first.textContent = final.textContent;
      }
    }, finalDelay);
    if (markerDelay !== null) {
      setTimeout(() => {
        marker = new FakeNode("marker", { "data-testid": "message-actions-copy" }, "");
        for (const assistant of assistants) assistant.marker = marker;
      }, markerDelay);
    }
  };

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
    .replace("const STABLE_TIME_MS = 1_500;", "const STABLE_TIME_MS = 20;")
    .replace("const COMPLETION_CONFIRMATION_MS = 3_000;", "const COMPLETION_CONFIRMATION_MS = 100;")
    .replace("const POLL_INTERVAL_MS = 200;", "const POLL_INTERVAL_MS = 10;")
    .replace("const RESPONSE_IDLE_TIMEOUT_MS = 300_000;", "const RESPONSE_IDLE_TIMEOUT_MS = 600;")
    .replace("const BUTTON_READY_TIMEOUT_MS = 5_000;", "const BUTTON_READY_TIMEOUT_MS = 200;")
    .replace("const SUBMIT_TIMEOUT_MS = 10_000;", "const SUBMIT_TIMEOUT_MS = 200;");
  vm.runInNewContext(source, context, { filename: SOURCE_PATH });
  const response = await new Promise((resolve) => {
    listeners[0]({ method: "chat", text: "问题", request_id: "req-stream" }, {}, resolve);
  });
  assert.equal(response.ok, true);
  assert.equal(response.result.text, expectText);
  assert.ok(progress.every((message) => message.request_id === "req-stream"));
}

async function runTimeoutScenario() {
  const source = fs.readFileSync(SOURCE_PATH, "utf8")
    .replace("const RESPONSE_IDLE_TIMEOUT_MS = 300_000;", "const RESPONSE_IDLE_TIMEOUT_MS = 100;");
  assert.match(source, /RESPONSE_IDLE_TIMEOUT_MS/);
}

(async () => {
  await runScenario({ finalDelay: 150, expectText: "这是一个完整项目" });
  await runScenario({ finalDelay: 150, replaceAssistant: true, expectText: "这是一个完整项目" });
  await runScenario({ finalDelay: 150, markerDelay: 120, expectText: "这是一个完整项目" });
  await runScenario({ finalDelay: 150, expectText: "这是一个完整项目" });
  await runTimeoutScenario();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
