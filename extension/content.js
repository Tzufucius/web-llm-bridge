(function (root) {
  "use strict";
  const provider = root.WebLLMBridge.detectProvider(root.location.href);
  if (!provider) return;
  const runtime = root.WebLLMBridge.createContentRuntime(provider.id);
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    Promise.resolve().then(() => runtime.handle(message || {})).then((result) => sendResponse({ ok: true, result })).catch((error) => sendResponse({ ok: false, error: { code: error?.code || "INTERNAL_ERROR", message: error?.message || "内容脚本内部错误" } }));
    return true;
  });
})(globalThis);
