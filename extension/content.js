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
const HISTORY_LOAD_TIMEOUT_MS = 60_000;
const HISTORY_POLL_INTERVAL_MS = 250;
const HISTORY_NO_GROWTH_ROUNDS = 3;
const MAX_HISTORY_LIMIT = 1_000;

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

async function sleep(milliseconds) {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
}

// =========================
// Markdown / LaTeX serializer
// =========================

function escapeTableCell(value) {
  return normalizeText(value).replace(/\|/g, "\\|");
}

function serializeMath(element) {
  const annotation = element.querySelector(
    'annotation[encoding="application/x-tex"]',
  );
  const tex = (annotation?.textContent || "").trim();
  if (!tex) {
    return "";
  }
  const display =
    element.matches('.katex-display, [display="block"], [display="true"]') ||
    Boolean(
      element.closest('.katex-display, [display="block"], [display="true"]'),
    );
  return display ? `\n$$\n${tex}\n$$\n` : `$${tex}$`;
}

function shouldSkipSerializedElement(element) {
  const tag = element.tagName.toLowerCase();
  return (
    tag === "script" ||
    tag === "style" ||
    tag === "noscript" ||
    element.getAttribute("aria-hidden") === "true" ||
    element.classList.contains("katex-html") ||
    element.classList.contains("katex-mathml") ||
    element.classList.contains("MathJax")
  );
}

function serializeTable(element) {
  const rows = [...element.querySelectorAll("tr")].map((row) =>
    [...row.querySelectorAll("th, td")].map((cell) =>
      escapeTableCell(cell.innerText || cell.textContent || ""),
    ),
  );
  const usableRows = rows.filter((row) => row.length > 0);
  if (usableRows.length === 0) {
    return "";
  }
  const width = Math.max(...usableRows.map((row) => row.length));
  const normalizeRow = (row) =>
    Array.from({ length: width }, (_, index) => row[index] || "");
  const header = normalizeRow(usableRows[0]);
  const separator = Array.from({ length: width }, () => "---");
  const lines = [
    `| ${header.join(" | ")} |`,
    `| ${separator.join(" | ")} |`,
  ];
  for (const row of usableRows.slice(1)) {
    lines.push(`| ${normalizeRow(row).join(" | ")} |`);
  }
  return `\n${lines.join("\n")}\n`;
}

function serializeList(element, ordered) {
  const items = [...element.children].filter(
    (child) => child.tagName?.toLowerCase() === "li",
  );
  return items
    .map((item, index) => {
      const value = serializeChildren(item).trim();
      return `${ordered ? `${index + 1}.` : "-"} ${value}`;
    })
    .join("\n");
}

function serializeNode(node) {
  if (node.nodeType === 3) {
    return node.nodeValue || "";
  }
  if (node.nodeType !== 1) {
    return "";
  }

  const element = node;
  const tag = element.tagName.toLowerCase();
  if (tag === "math" || element.classList.contains("katex")) {
    return serializeMath(element);
  }
  if (shouldSkipSerializedElement(element)) {
    return "";
  }
  if (tag === "br") {
    return "\n";
  }
  if (tag === "hr") {
    return "\n---\n";
  }
  if (tag === "pre") {
    const code = element.innerText || element.textContent || "";
    return `\n\`\`\`\n${code.replace(/\n+$/, "")}\n\`\`\`\n`;
  }
  if (tag === "code") {
    return `\`${(element.innerText || element.textContent || "").trim()}\``;
  }
  if (tag === "a") {
    const text = serializeChildren(element).trim();
    const href = element.getAttribute("href");
    return href ? `[${text || href}](${href})` : text;
  }
  if (["strong", "b"].includes(tag)) {
    return `**${serializeChildren(element).trim()}**`;
  }
  if (["em", "i"].includes(tag)) {
    return `*${serializeChildren(element).trim()}*`;
  }
  if (/^h[1-6]$/.test(tag)) {
    return `\n${"#".repeat(Number(tag[1]))} ${serializeChildren(element).trim()}\n`;
  }
  if (tag === "ul" || tag === "ol") {
    return `\n${serializeList(element, tag === "ol")}\n`;
  }
  if (tag === "blockquote") {
    const value = cleanMarkdown(serializeChildren(element));
    return `\n${value
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n")}\n`;
  }
  if (tag === "table") {
    return serializeTable(element);
  }
  if (["p", "div", "section", "article", "li"].includes(tag)) {
    return `\n${serializeChildren(element)}\n`;
  }
  return serializeChildren(element);
}

function serializeChildren(element) {
  return [...element.childNodes].map((child) => serializeNode(child)).join("");
}

function cleanMarkdown(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function serializeMessageToMarkdown(node) {
  const value = cleanMarkdown(serializeNode(node));
  return value || cleanMarkdown(node.innerText || "");
}

// =========================
// History collector
// =========================

const turnCache = new Map();
const fallbackNodeIds = new WeakMap();
let fallbackSequence = 0;
let turnOrder = [];
let historyLoadPromise = null;
let historyCollectionActive = false;
let observerCaptureScheduled = false;
let cachedConversationLocation = null;

function getConversationLocation() {
  return `${window.location.origin}${window.location.pathname}`;
}

function resetCacheWhenConversationChanges() {
  const locationKey = getConversationLocation();
  if (cachedConversationLocation === null) {
    cachedConversationLocation = locationKey;
    return;
  }
  if (cachedConversationLocation === locationKey) {
    return;
  }
  cachedConversationLocation = locationKey;
  turnCache.clear();
  turnOrder = [];
}

function findTurnContainer(node) {
  return (
    node.closest("[data-turn-id]") ||
    node.closest('[data-testid^="conversation-turn-"]') ||
    node.closest("[data-turn]") ||
    node
  );
}

function getTurnIdentity(node, occurrences = new Map()) {
  const container = findTurnContainer(node);
  for (const attribute of ["data-turn-id", "data-testid", "data-turn"]) {
    const value = container.getAttribute(attribute);
    if (value) {
      return `${attribute}:${value}`;
    }
  }
  if (!fallbackNodeIds.has(container)) {
    fallbackNodeIds.set(container, `node:${++fallbackSequence}`);
  }
  const nodeId = fallbackNodeIds.get(container);
  if (nodeId) {
    return nodeId;
  }
  const role = node.getAttribute("data-message-author-role") || "unknown";
  const signature = `${role}:${normalizeText(node.innerText || "")}`;
  const occurrence = occurrences.get(signature) || 0;
  occurrences.set(signature, occurrence + 1);
  return `fallback:${role}:${hashText(signature)}:${occurrence}`;
}

function hashText(value) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

function captureVisibleTurns({ prepend = false } = {}) {
  resetCacheWhenConversationChanges();
  const occurrences = new Map();
  const records = [];
  for (const node of document.querySelectorAll(MESSAGE_SELECTOR)) {
    const role = node.getAttribute("data-message-author-role");
    if (role !== "user" && role !== "assistant") {
      continue;
    }
    const content = serializeMessageToMarkdown(node);
    if (!content) {
      continue;
    }
    records.push({
      id: getTurnIdentity(node, occurrences),
      role,
      content,
    });
  }

  const newIds = [];
  for (const record of records) {
    const previous = turnCache.get(record.id);
    if (!previous) {
      turnCache.set(record.id, { role: record.role, content: record.content });
      newIds.push(record.id);
    } else if (record.content.length >= previous.content.length) {
      turnCache.set(record.id, { role: record.role, content: record.content });
    }
  }
  if (newIds.length > 0) {
    const uniqueNewIds = newIds.filter((id) => !turnOrder.includes(id));
    if (prepend) {
      turnOrder = [...uniqueNewIds, ...turnOrder];
    } else {
      turnOrder = [...turnOrder, ...uniqueNewIds];
    }
  }
  return { newCount: newIds.length, total: turnOrder.length };
}

function getCachedMessages() {
  return turnOrder
    .map((id) => turnCache.get(id))
    .filter(Boolean)
    .map((record) => ({ role: record.role, content: record.content }));
}

function findConversationScrollContainer() {
  const anchor = document.querySelector(MESSAGE_SELECTOR);
  let current = anchor;
  while (current && current !== document.body) {
    const style = window.getComputedStyle(current);
    if (
      ["auto", "scroll"].includes(style.overflowY) &&
      current.scrollHeight > current.clientHeight + 1
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return document.scrollingElement || document.documentElement;
}

function scrollTopOf(container) {
  return container === document.scrollingElement ? window.scrollY : container.scrollTop;
}

function setScrollTop(container, value) {
  if (container === document.scrollingElement) {
    window.scrollTo(0, value);
  } else {
    container.scrollTop = value;
  }
}

function maxScrollTop(container) {
  return Math.max(0, container.scrollHeight - container.clientHeight);
}

function normalizeHistoryOptions(options = {}) {
  const full = options.full === true;
  if (full) {
    return { limit: null, full: true };
  }
  const limit = options.limit == null ? null : Number(options.limit);
  if (
    limit !== null &&
    (!Number.isInteger(limit) || limit < 1 || limit > MAX_HISTORY_LIMIT)
  ) {
    throw new ContentBridgeError(
      "INPUT_FAILED",
      `历史消息数量必须是 1 到 ${MAX_HISTORY_LIMIT} 的正整数`,
    );
  }
  return { limit, full };
}

async function collectHistoryInternal(options) {
  const { limit, full } = normalizeHistoryOptions(options);
  const container = findConversationScrollContainer();
  const originalScrollTop = scrollTopOf(container);
  const originalWasNearBottom =
    maxScrollTop(container) - originalScrollTop <= container.clientHeight * 1.5;
  const deadline = performance.now() + HISTORY_LOAD_TIMEOUT_MS;
  let noGrowthRounds = 0;
  let truncated = false;
  historyCollectionActive = true;

  try {
    captureVisibleTurns({ prepend: false });
    while (performance.now() < deadline) {
      const messages = getCachedMessages();
      if (!full && (limit === null || messages.length >= limit)) {
        break;
      }

      const atTop = scrollTopOf(container) <= 1;
      if (atTop && noGrowthRounds >= HISTORY_NO_GROWTH_ROUNDS) {
        break;
      }
      const beforeCount = turnOrder.length;
      const currentTop = scrollTopOf(container);
      // Keep an overlap between virtualized viewport batches so that a fast
      // scroll cannot skip turns that are removed from the DOM immediately.
      const step = Math.max(80, Math.floor(container.clientHeight * 0.75));
      setScrollTop(container, Math.max(0, currentTop - step));
      await sleep(HISTORY_POLL_INTERVAL_MS);
      const captured = captureVisibleTurns({ prepend: true });
      if (captured.newCount === 0 && scrollTopOf(container) <= 1) {
        noGrowthRounds += 1;
      } else if (captured.newCount > 0 || turnOrder.length > beforeCount) {
        noGrowthRounds = 0;
      } else {
        noGrowthRounds = Math.max(0, noGrowthRounds - 1);
      }
    }
    const messages = getCachedMessages();
    // Reaching the top with fewer messages means the conversation is shorter
    // than the requested limit, not that history loading was truncated.
    truncated = performance.now() >= deadline;
    return {
      messages: full || limit === null ? messages : messages.slice(-limit),
      truncated,
    };
  } finally {
    historyCollectionActive = false;
    const restoredTop = originalWasNearBottom
      ? maxScrollTop(container)
      : Math.min(originalScrollTop, maxScrollTop(container));
    setScrollTop(container, restoredTop);
  }
}

function collectHistory(options = {}) {
  if (historyLoadPromise) {
    return historyLoadPromise;
  }
  historyLoadPromise = collectHistoryInternal(options).finally(() => {
    historyLoadPromise = null;
  });
  return historyLoadPromise;
}

function scheduleVisibleCapture() {
  if (observerCaptureScheduled) {
    return;
  }
  observerCaptureScheduled = true;
  setTimeout(() => {
    observerCaptureScheduled = false;
    captureVisibleTurns({ prepend: historyCollectionActive });
  }, 100);
}

function startTurnObserver() {
  if (!document.body) {
    return;
  }
  const observer = new MutationObserver(scheduleVisibleCapture);
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
  });
}

// =========================
// Chat operations
// =========================

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
  await waitForResponseComplete();
  return { text: serializeMessageToMarkdown(getLastAssistant()) };
}

async function handleMethod(message) {
  if (message.method === "ping") {
    return { ready: true };
  }
  if (message.method === "get_messages") {
    return collectHistory({ limit: message.limit, full: message.full === true });
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

startTurnObserver();
