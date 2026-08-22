(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.error = function error(code, message, safeToRetry) {
    const value = new Error(message);
    value.code = code;
    value.safeToRetry = safeToRetry === true;
    return value;
  };
  bridge.sleep = function sleep(milliseconds) {
    return new Promise((resolve) => root.setTimeout(resolve, milliseconds));
  };
  bridge.normalizeText = function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  };
})(globalThis);
