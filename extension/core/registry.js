(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  const providers = new Map();

  bridge.registerProvider = function registerProvider(provider) {
    if (!provider || typeof provider.id !== "string" || !provider.id) {
      throw new Error("Provider 必须提供非空 id");
    }
    if (providers.has(provider.id)) {
      throw new Error(`Provider 已注册：${provider.id}`);
    }
    providers.set(provider.id, Object.freeze(provider));
  };
  bridge.getProvider = function getProvider(id) {
    return providers.get(id) || null;
  };
  bridge.listProviders = function listProviders() {
    return [...providers.values()];
  };
  bridge.detectProvider = function detectProvider(url) {
    return bridge.listProviders().find((provider) => provider.matchesUrl(url)) || null;
  };
})(globalThis);
