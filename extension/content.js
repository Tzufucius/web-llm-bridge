const PROMPT_SELECTORS = [
  "#prompt-textarea",
  '[contenteditable="true"][role="textbox"]',
];
const SEND_BUTTON_SELECTORS = [
  "#composer-submit-button",
  '[data-testid="send-button"]',
  'button[aria-label="Send prompt"]',
];
const STOP_BUTTON_SELECTORS = [
  '[data-testid="stop-button"]',
  'button[aria-label*="Stop"]',
];
const MESSAGE_SELECTOR = "[data-message-author-role]";
const ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]';
const USER_SELECTOR = '[data-message-author-role="user"]';
const STABLE_TIME_MS = 1_500;
const POLL_INTERVAL_MS = 200;
const RESPONSE_TIMEOUT_MS = 180_000;
const BUTTON_READY_TIMEOUT_MS = 5_000;
const SUBMIT_TIMEOUT_MS = 10_000;

class ContentBridgeError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function isVisible(element) {
  if (!element) {
    return false;
  }
  const style = window.getComputedStyle(element);
  return (
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    element.getClientRects().length > 0
  );
}

function findVisible(selectors) {
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (isVisible(element)) {
      return element;
    }
  }
  return null;
}

function getPrompt() {
  const prompt = findVisible(PROMPT_SELECTORS);
  if (!prompt) {
    throw new ContentBridgeError("PROMPT_NOT_FOUND", "未找到 ChatGPT 输入框");
  }
  return prompt;
}

function getSendButton() {
  const button = findVisible(SEND_BUTTON_SELECTORS);
  if (!button) {
    throw new ContentBridgeError(
      "SEND_BUTTON_NOT_FOUND",
      "未找到可靠的 ChatGPT 发送按钮",
    );
  }
  return button;
}

function readPromptText(prompt) {
  if (typeof prompt.value === "string") {
    return prompt.value;
  }
  return prompt.innerText || "";
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function dispatchInput(prompt, text) {
  prompt.dispatchEvent(
    new InputEvent("input", {
      bubbles: true,
      inputType: "insertText",
      data: text,
    }),
  );
}

function setFormValue(prompt, text, emitInput = true) {
  const prototype = Object.getPrototypeOf(prompt);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor?.set) {
    descriptor.set.call(prompt, text);
  } else {
    prompt.value = text;
  }
  if (emitInput) {
    dispatchInput(prompt, text);
  }
}

function selectPromptContents(prompt) {
  const range = document.createRange();
  range.selectNodeContents(prompt);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  return range;
}

function clearContentEditable(prompt) {
  prompt.focus();
  const range = selectPromptContents(prompt);
  const deleted = document.execCommand("delete", false);
  if (!deleted) {
    range.deleteContents();
    range.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    dispatchInput(prompt, "");
  }
}

function insertContentEditableText(prompt, text) {
  prompt.focus();
  clearContentEditable(prompt);
  let inserted = document.execCommand("insertText", false, text);
  if (!inserted) {
    const range = document.createRange();
    range.selectNodeContents(prompt);
    range.deleteContents();
    range.collapse(true);
    range.insertNode(document.createTextNode(text));
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    dispatchInput(prompt, text);
    inserted = true;
  }
  return inserted;
}

function writePrompt(prompt, text) {
  if (prompt.isContentEditable) {
    insertContentEditableText(prompt, text);
  } else if ("value" in prompt) {
    setFormValue(prompt, "", false);
    setFormValue(prompt, text);
  } else {
    throw new ContentBridgeError("INPUT_FAILED", "ChatGPT 输入框不支持文本写入");
  }

  if (normalizeText(readPromptText(prompt)) !== normalizeText(text)) {
    throw new ContentBridgeError("INPUT_FAILED", "文本未成功写入 ChatGPT 输入框");
  }
}

function isEnabled(button) {
  return (
    !button.disabled &&
    button.getAttribute("aria-disabled") !== "true" &&
    !button.hasAttribute("disabled")
  );
}

async function waitForEnabledButton() {
  const deadline = performance.now() + BUTTON_READY_TIMEOUT_MS;
  while (performance.now() < deadline) {
    const button = findVisible(SEND_BUTTON_SELECTORS);
    if (button && isEnabled(button)) {
      return button;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new ContentBridgeError(
    "SEND_BUTTON_NOT_FOUND",
    "ChatGPT 发送按钮不可用或页面结构发生变化",
  );
}

function isGenerating() {
  return Boolean(findVisible(STOP_BUTTON_SELECTORS));
}

function assistantCount() {
  return document.querySelectorAll(ASSISTANT_SELECTOR).length;
}

function userCount() {
  return document.querySelectorAll(USER_SELECTOR).length;
}

function getLastAssistant() {
  const nodes = document.querySelectorAll(ASSISTANT_SELECTOR);
  if (nodes.length === 0) {
    throw new ContentBridgeError("RESPONSE_NOT_FOUND", "未找到 Assistant 回复");
  }
  return nodes[nodes.length - 1];
}

function getMessages() {
  const messages = [];
  for (const node of document.querySelectorAll(MESSAGE_SELECTOR)) {
    const role = node.getAttribute("data-message-author-role");
    if (role !== "user" && role !== "assistant") {
      continue;
    }
    const content = (node.innerText || "").trim();
    if (content) {
      messages.push({ role, content });
    }
  }
  return messages;
}

async function sleep(milliseconds) {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function sendText(text) {
  if (isGenerating()) {
    throw new ContentBridgeError("BUSY", "ChatGPT 当前仍在生成回复");
  }
  const prompt = getPrompt();
  writePrompt(prompt, text);
  const button = await waitForEnabledButton();
  button.click();
}

async function waitForUserSubmitted(oldCount) {
  const deadline = performance.now() + SUBMIT_TIMEOUT_MS;
  while (performance.now() < deadline) {
    if (userCount() > oldCount) {
      return;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new ContentBridgeError(
    "SEND_FAILED",
    "消息点击发送后未确认提交成功",
  );
}

async function waitForNewAssistant(oldCount) {
  const deadline = performance.now() + RESPONSE_TIMEOUT_MS;
  while (performance.now() < deadline) {
    if (assistantCount() > oldCount) {
      return;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new ContentBridgeError("RESPONSE_TIMEOUT", "等待新的 Assistant 消息超时");
}

async function waitForResponseComplete() {
  const deadline = performance.now() + RESPONSE_TIMEOUT_MS;
  let lastText = null;
  let stableSince = null;

  while (performance.now() < deadline) {
    let currentText;
    try {
      currentText = (getLastAssistant().innerText || "").trim();
    } catch (error) {
      if (error instanceof ContentBridgeError) {
        throw error;
      }
      throw new ContentBridgeError("DOM_CHANGED", "读取 Assistant 回复时页面结构发生变化");
    }

    const now = performance.now();
    if (currentText !== lastText) {
      lastText = currentText;
      stableSince = currentText ? now : null;
    } else if (
      currentText &&
      stableSince !== null &&
      now - stableSince >= STABLE_TIME_MS &&
      !isGenerating()
    ) {
      return currentText;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new ContentBridgeError("RESPONSE_TIMEOUT", "等待 ChatGPT 回复超时");
}

async function chat(text) {
  if (typeof text !== "string" || !text.trim()) {
    throw new ContentBridgeError("INPUT_FAILED", "消息不能为空");
  }
  const beforeUserCount = userCount();
  const beforeAssistantCount = assistantCount();
  await sendText(text);
  await waitForUserSubmitted(beforeUserCount);
  await waitForNewAssistant(beforeAssistantCount);
  const finalText = await waitForResponseComplete();
  return { text: finalText };
}

async function handleMethod(message) {
  if (message.method === "ping") {
    return { ready: true };
  }
  if (message.method === "get_messages") {
    return { messages: getMessages() };
  }
  if (message.method === "chat") {
    return chat(message.text);
  }
  throw new ContentBridgeError("INTERNAL_ERROR", `未知内容脚本方法：${message.method}`);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  Promise.resolve()
    .then(() => handleMethod(message || {}))
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => {
      sendResponse({
        ok: false,
        error: {
          code: error?.code || "INTERNAL_ERROR",
          message: error?.message || "ChatGPT 内容脚本内部错误",
        },
      });
    });
  return true;
});
