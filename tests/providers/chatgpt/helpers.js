const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../../..");
class FakeNode {
  constructor(kind, attrs = {}, text = "") { this.kind = kind; this.attrs = { ...attrs }; this.innerText = text; this.textContent = text; this.childNodes = []; this.children = []; this.parentElement = null; this.nodeType = 1; this.tagName = kind === "button" ? "BUTTON" : "DIV"; this.disabled = false; this.isContentEditable = false; this.value = ""; this.childElementCount = 0; this.scrollTop = 0; this.scrollHeight = 100; this.clientHeight = 100; this.classList = { contains: (name) => (this.attrs.class || "").split(/\s+/).includes(name) }; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }
  matches(selector) {
    if (selector.includes(",")) return selector.split(",").some((part) => this.matches(part.trim()));
    if (selector === "#prompt-textarea") return this.kind === "prompt";
    if (selector === "#composer-submit-button" || selector === '[data-testid="send-button"]' || selector === 'button[aria-label="Send prompt"]') return this.kind === "button";
    if (selector === '[data-testid="stop-button"]' || selector === 'button[aria-label*="Stop"]') return this.kind === "stop";
    if (selector === "main" || selector === '[role="main"]') return this.kind === "main";
    if (selector === '[data-message-author-role]') return Boolean(this.attrs["data-message-author-role"]);
    if (selector.includes('data-message-author-role="user"')) return this.kind === "user";
    if (selector.includes('data-message-author-role="assistant"')) return this.kind === "assistant";
    if (selector.includes('data-testid*="')) { const token = selector.match(/data-testid\*="([^"]+)/)?.[1]; return Boolean(token && String(this.attrs["data-testid"] || "").includes(token)); }
    if (selector.includes("aria-label*=")) { const token = selector.match(/aria-label\*="([^"]+)/)?.[1]; return Boolean(token && String(this.attrs["aria-label"] || "").toLowerCase().includes(token.toLowerCase())); }
    if (selector.includes("class*=")) { const token = selector.match(/class\*="([^"]+)/)?.[1]; return Boolean(token && String(this.attrs.class || "").includes(token)); }
    if (selector === "[aria-live]") return this.attrs["aria-live"] != null;
    if (selector === '[role="status"]') return this.attrs.role === "status";
    if (selector === '[role="log"]') return this.attrs.role === "log";
    if (selector === '[aria-busy="true"]') return this.attrs["aria-busy"] === "true";
    if (selector.includes("[data-status]")) return this.attrs["data-status"] != null;
    return false;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  getClientRects() { return [{}]; }
  dispatchEvent() {}
  focus() {}
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) { return this.marker?.matches(selector) ? [this.marker] : []; }
}
function loadContentRuntime({ document, progress = [], timingOverrides = {}, onScroll = null }) {
  const listeners = [];
  const context = { console, URL, document, Node: { ELEMENT_NODE: 1 }, performance, setTimeout, clearTimeout, InputEvent: class InputEvent {}, MutationObserver: class { observe() {} }, location: { href: "https://chatgpt.com/c/test", origin: "https://chatgpt.com", pathname: "/c/test" }, scrollY: 0, getComputedStyle: () => ({ display: "block", visibility: "visible", overflowY: "visible" }), getSelection: () => ({ removeAllRanges() {}, addRange() {} }), scrollTo(_x, y) { context.scrollY = y; onScroll?.(y); }, chrome: { runtime: { onMessage: { addListener: (listener) => listeners.push(listener) }, sendMessage: (message) => { progress.push(message); return Promise.resolve(); } } } };
  context.globalThis = context;
  context.WebLLMBridge = { timing: { stableTimeMs: 20, completionConfirmationMs: 40, pollIntervalMs: 10, responseIdleTimeoutMs: 500, progressIntervalMs: 20, pageReadyTimeoutMs: 500, buttonReadyTimeoutMs: 500, submissionConfirmationTimeoutMs: 500, historyLoadTimeoutMs: 100, historyPollIntervalMs: 10, ...timingOverrides } };
  vm.createContext(context);
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "extension", "manifest.json"), "utf8"));
  for (const file of manifest.content_scripts[0].js) vm.runInContext(fs.readFileSync(path.join(ROOT, "extension", file), "utf8"), context, { filename: file });
  return { context, listeners };
}
module.exports = { FakeNode, loadContentRuntime };
