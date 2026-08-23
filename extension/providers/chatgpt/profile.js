(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.ChatGPTProfile = {
    id: "chatgpt",
    defaultUrl: "https://chatgpt.com/",
    hosts: ["chatgpt.com", "www.chatgpt.com"],
    capabilities: Object.freeze({
      chat: true,
      getMessages: true,
      history: true,
      fullHistory: true,
      markdown: true,
      latex: true,
      persistentConversation: true,
      artifacts: true,
      images: true,
    }),
    timing: {
      stableTimeMs: 1_500,
      completionConfirmationMs: 3_000,
      pollIntervalMs: 200,
      responseIdleTimeoutMs: 300_000,
      progressIntervalMs: 1_500,
      pageReadyTimeoutMs: 30_000,
      buttonReadyTimeoutMs: 30_000,
      submissionConfirmationTimeoutMs: 60_000,
      historyLoadTimeoutMs: 60_000,
      historyPollIntervalMs: 250,
    },
    selectors: {
      prompt: ["#prompt-textarea", '[contenteditable="true"][role="textbox"]'],
      send: ["#composer-submit-button", '[data-testid="send-button"]', 'button[aria-label="Send prompt"]'],
      stop: ['[data-testid="stop-button"]', 'button[aria-label*="Stop"]'],
      completion: ['[data-testid*="copy"]', '[data-testid*="message-actions"]', 'button[aria-label*="Copy" i]', 'button[aria-label*="复制"]'],
      message: '[data-message-author-role]', user: '[data-message-author-role="user"]', assistant: '[data-message-author-role="assistant"]',
      tool: ['[data-testid*="tool"]', '[data-testid*="function"]', '[data-testid*="browser"]', '[data-testid*="search"]', '[data-testid*="code"]', '[data-testid*="thinking"]', '[aria-label*="tool" i]', '[aria-label*="function" i]', '[aria-label*="browser" i]', '[aria-label*="search" i]', '[aria-label*="code" i]', '[class*="tool"]', '[class*="thinking"]'],
      status: ['[aria-live]', '[role="status"]', '[role="log"]', '[aria-busy="true"]', '[data-testid*="status"]', '[data-testid*="progress"]', '[data-testid*="loading"]', '[data-testid*="response"]', '[data-status]'],
    },
    matchesUrl(value) {
      try { const url = new URL(value); return url.protocol === "https:" && this.hosts.includes(url.hostname); } catch (_error) { return false; }
    },
    normalizeUrl(value) {
      if (!this.matchesUrl(value)) return null;
      const url = new URL(value); const path = url.pathname || "/";
      return `${url.origin}${path === "/" ? "/" : path.replace(/\/+$/, "")}`;
    },
  };
})(globalThis);
