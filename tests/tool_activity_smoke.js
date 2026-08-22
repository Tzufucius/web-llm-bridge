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
    this.classList = {
      contains: (name) => (this.attrs.class || "").split(/\s+/).includes(name),
    };
  }

  getAttribute(name) {
    return this.attrs[name] ?? null;
  }

  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name);
  }

  matches(selector) {
    if (selector.includes(",")) {
      return selector.split(",").some((part) => this.matches(part.trim()));
    }
    if (selector === "#prompt-textarea") return this.kind === "prompt";
    if (selector === "#composer-submit-button") return this.kind === "button";
    if (selector === 'button[aria-label="Send prompt"]') return this.kind === "button";
    if (selector === '[data-testid="send-button"]') return this.kind === "button";
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
    if (selector.includes("class*=")) {
      const token = selector.match(/class\*="([^"]+)/)?.[1];
      return Boolean(token && String(this.attrs.class || "").includes(token));
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

  getClientRects() {
    return [{}];
  }

  dispatchEvent() {}
  focus() {}
  querySelectorAll() { return []; }
  querySelector() { return null; }
}

async function runSmoke({ complete = true } = {}) {
  const users = [];
  const assistants = [];
  let toolNode = null;
  let generating = false;
  let submitted = false;
  const progress = [];

  const prompt = new FakeNode("prompt");
  const sendButton = new FakeNode("button");
  const main = new FakeNode("main");
  const body = new FakeNode("body");
  const stopButton = new FakeNode("stop", { "data-testid": "stop-button" });
  const allNodes = () => [
    main,
    body,
    prompt,
    sendButton,
    ...(toolNode ? [toolNode] : []),
    ...(generating ? [stopButton] : []),
    ...users,
    ...assistants,
  ];

  sendButton.click = () => {
    if (submitted) return;
    submitted = true;
    generating = true;
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "审查"));
    setTimeout(() => {
      toolNode = new FakeNode("tool", { "data-testid": "tool-call" }, "工具调用 1");
    }, 40);
    for (let index = 2; index <= 5; index += 1) {
      setTimeout(() => {
        if (toolNode) {
          toolNode.innerText = `工具调用 ${index}`;
          toolNode.textContent = toolNode.innerText;
          toolNode.attrs["data-status"] = `running-${index}`;
        }
      }, 40 * index);
    }
    if (!complete) return;
    setTimeout(() => {
      generating = false;
      assistants.push(new FakeNode("assistant", { "data-message-author-role": "assistant" }, "最终回复"));
    }, 300);
  };

  const document = {
    body,
    scrollingElement: body,
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
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
    .replace("const COMPLETION_CONFIRMATION_MS = 3_000;", "const COMPLETION_CONFIRMATION_MS = 40;")
    .replace("const POLL_INTERVAL_MS = 200;", "const POLL_INTERVAL_MS = 10;")
    .replace("const RESPONSE_IDLE_TIMEOUT_MS = 300_000;", "const RESPONSE_IDLE_TIMEOUT_MS = 250;")
    .replace("const PROGRESS_INTERVAL_MS = 1_500;", "const PROGRESS_INTERVAL_MS = 20;")
    .replace("const BUTTON_READY_TIMEOUT_MS = 5_000;", "const BUTTON_READY_TIMEOUT_MS = 500;")
    .replace("const SUBMIT_TIMEOUT_MS = 10_000;", "const SUBMIT_TIMEOUT_MS = 500;");
  vm.runInNewContext(source, context, { filename: SOURCE_PATH });

  const response = await new Promise((resolve) => {
    listeners[0]({ method: "chat", text: "审查", request_id: "req-tool" }, {}, resolve);
  });
  if (!complete) {
    assert.equal(response.ok, false);
    assert.equal(response.error.code, "RESPONSE_TIMEOUT");
    return;
  }
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "最终回复");
  assert.ok(progress.some((message) => message.phase === "tool_call"));
  assert.ok(progress.every((message) => message.request_id === "req-tool"));
}

runSmoke()
  .then(() => runSmoke({ complete: false }))
  .catch((error) => {
  console.error(error);
  process.exitCode = 1;
  });
