(function (root) {
  "use strict";
  const bridge = (root.WebLLMBridge = root.WebLLMBridge || {});
  bridge.createContentRuntime = function createContentRuntime(providerId) {
    const provider = bridge.getProvider(providerId);
    if (!provider) throw new Error(`未注册 Provider：${providerId}`);
    const timing = { ...(provider.timing || {}), ...(bridge.timing || {}) };
    const adapter = provider.adapter;
    const history = bridge.createHistory(provider, timing);
    let revision = 0;
    let scheduled = false;

    function promptText(prompt) { return typeof prompt?.value === "string" ? prompt.value : prompt?.innerText || ""; }
    function input(prompt, text) { prompt.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text })); }
    function write(prompt, text) {
      if (prompt.isContentEditable) {
        prompt.focus(); const range = document.createRange(); range.selectNodeContents(prompt); const selection = root.getSelection(); selection.removeAllRanges(); selection.addRange(range);
        if (!document.execCommand("delete", false)) { range.deleteContents(); input(prompt, ""); }
        if (!document.execCommand("insertText", false, text)) { range.selectNodeContents(prompt); range.deleteContents(); range.insertNode(document.createTextNode(text)); input(prompt, text); }
      } else if ("value" in prompt) { const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(prompt), "value"); if (descriptor?.set) descriptor.set.call(prompt, ""); else prompt.value = ""; if (descriptor?.set) descriptor.set.call(prompt, text); else prompt.value = text; input(prompt, text); }
      else throw bridge.error("INPUT_FAILED", "输入框不支持文本写入");
      if (bridge.normalizeText(promptText(prompt)) !== bridge.normalizeText(text)) throw bridge.error("INPUT_FAILED", "文本未成功写入输入框");
    }
    async function waitFor(find, code, message, timeout) { const deadline = root.performance.now() + timeout; while (root.performance.now() < deadline) { const value = find(); if (value) return value; await bridge.sleep(timing.pollIntervalMs); } throw bridge.error(code, message); }
    async function sendText(text) {
      if (adapter.isGenerating()) throw bridge.error("BUSY", "页面当前仍在生成回复");
      const deadline = root.performance.now() + timing.pageReadyTimeoutMs; let lastError;
      while (root.performance.now() < deadline) { try { const remaining = Math.max(1, deadline - root.performance.now()); const prompt = await waitFor(adapter.findPrompt, "PROMPT_NOT_FOUND", "页面仍在加载，输入框尚未就绪", remaining); write(prompt, text); const button = await waitFor(() => { const candidate = adapter.findSendButton(); return candidate && adapter.isEnabled(candidate) ? candidate : null; }, "SEND_BUTTON_NOT_FOUND", "发送按钮不可用或页面结构发生变化", Math.min(remaining, timing.buttonReadyTimeoutMs)); button.click(); return; } catch (error) { lastError = error; if (!["PROMPT_NOT_FOUND", "SEND_BUTTON_NOT_FOUND", "INPUT_FAILED"].includes(error?.code)) throw error; await bridge.sleep(timing.pollIntervalMs); } }
      throw bridge.error("PAGE_NOT_READY", lastError ? "页面在限定时间内未完成加载，输入框或发送按钮仍不可用" : "页面在限定时间内未完成加载");
    }
    function progress(requestId, phase, startedAt, activityAt) { if (typeof requestId !== "string" || !requestId) return; const now = root.performance.now(); try { const result = chrome.runtime.sendMessage({ type: "chat_progress", request_id: requestId, phase, elapsed_ms: Math.max(0, Math.round(now - startedAt)), idle_ms: Math.max(0, Math.round(now - activityAt)) }); result?.catch?.(() => {}); } catch (_error) {} }
    async function waitForSubmitted(beforeUsers, baseline, requestId, startedAt) {
      const deadline = root.performance.now() + timing.submissionConfirmationTimeoutMs; let lastRevision = revision; let lastProgress = startedAt; let lastActivity = startedAt; progress(requestId, "working", startedAt, lastActivity);
      while (root.performance.now() < deadline) { if (adapter.getUsers().length > beforeUsers) return; const prompt = adapter.findPrompt(); if ((prompt && bridge.normalizeText(promptText(prompt)) === "") || adapter.isGenerating() || (adapter.getLastAssistant() && adapter.getLastAssistant() !== baseline)) return; const now = root.performance.now(); if (revision !== lastRevision) { lastRevision = revision; lastActivity = now; } if (now - lastProgress >= timing.progressIntervalMs) { progress(requestId, "working", startedAt, lastActivity); lastProgress = now; } await bridge.sleep(timing.pollIntervalMs); }
      throw bridge.error("SEND_FAILED", "页面在 60 秒内未确认消息提交，可能仍在加载");
    }
    function responseSnapshot(node) {
      const text = bridge.normalizeText(node?.innerText || node?.textContent || "");
      const artifacts = node && adapter.getArtifacts ? adapter.getArtifacts(node) : [];
      const signature = JSON.stringify([text, artifacts.map((item) => [item.turn_id, item.index, item.width, item.height, item.ready === true, item._source || ""])]);
      return { text, artifacts, signature, ready: artifacts.every((item) => item.ready === true) };
    }
    async function waitForComplete(requestId, baseline, startedAt) {
      const baselineSnapshot = responseSnapshot(baseline); let lastActivity = startedAt; let lastRevision = revision; let lastResponse = baselineSnapshot; let lastActivitySignature = adapter.activitySnapshot().signature; let lastMarker = adapter.hasCompletionMarker(baseline); let lastNode = baseline; let stableSince = null; let candidate = null; let candidateSince = null; let lastProgress = startedAt; let lastPhase = "thinking"; let observed = false; let kind = "thinking";
      progress(requestId, "thinking", startedAt, lastActivity);
      while (true) {
        const now = root.performance.now(); const assistant = adapter.getLastAssistant(); const snapshot = responseSnapshot(assistant); const activity = adapter.activitySnapshot(); const marker = adapter.hasCompletionMarker(assistant); const responseChanged = snapshot.signature !== lastResponse.signature; const activityChanged = activity.signature !== lastActivitySignature; const markerChanged = marker !== lastMarker; const revisionChanged = revision !== lastRevision; const changed = revisionChanged || responseChanged || activityChanged || markerChanged;
        const nodeChanged = assistant !== null && assistant !== lastNode;
        const newReplyObserved = Boolean(assistant && (assistant !== baseline || snapshot.signature !== baselineSnapshot.signature));
        const responseExists = Boolean(newReplyObserved && (snapshot.text || snapshot.artifacts.length));
        if (changed) { lastActivity = now; lastRevision = revision; lastResponse = snapshot; lastActivitySignature = activity.signature; lastMarker = marker; observed = true; kind = activity.toolCall ? "tool_call" : "working"; }
        if (nodeChanged) lastNode = assistant;
        if (responseChanged || nodeChanged) stableSince = now;
        if (responseExists && (!snapshot.artifacts.length || snapshot.ready) && !adapter.isGenerating()) {
          const serialized = bridge.serializeMessageToMarkdown(assistant, adapter.serializer);
          if (candidate !== serialized || responseChanged || markerChanged) { candidate = serialized; candidateSince = now; }
          else if (candidateSince === null) candidateSince = now;
        } else { candidate = null; candidateSince = null; }
        const phase = snapshot.text ? "streaming" : kind === "tool_call" && now - lastActivity <= timing.progressIntervalMs ? "tool_call" : observed && now - lastActivity <= timing.progressIntervalMs ? "working" : "thinking";
        if (phase !== lastPhase || now - lastProgress >= timing.progressIntervalMs) { progress(requestId, phase, startedAt, lastActivity); lastPhase = phase; lastProgress = now; }
        if (responseExists && (!snapshot.artifacts.length || snapshot.ready) && stableSince !== null && now - stableSince >= timing.stableTimeMs && now - lastActivity >= timing.stableTimeMs && candidateSince !== null && now - candidateSince >= timing.completionConfirmationMs && !adapter.isGenerating()) {
          const finalAssistant = adapter.getLastAssistant(); const finalSnapshot = responseSnapshot(finalAssistant); const finalText = finalAssistant && bridge.serializeMessageToMarkdown(finalAssistant, adapter.serializer);
          if (finalText === candidate && finalSnapshot.signature === snapshot.signature && (!finalSnapshot.artifacts.length || finalSnapshot.ready)) return { text: finalText || "", artifacts: finalSnapshot.artifacts };
          candidate = null; candidateSince = null; stableSince = null;
        }
        if (now - lastActivity >= timing.responseIdleTimeoutMs) throw bridge.error("RESPONSE_TIMEOUT", "连续 5 分钟未检测到页面更新，可能仍在思考或页面结构已变化");
        await bridge.sleep(timing.pollIntervalMs);
      }
    }
    async function waitForArtifact(artifact) {
      if (!Number.isInteger(artifact?.index) || typeof artifact?.turn_id !== "string" || !artifact.turn_id) return artifact;
      const timeout = Number.isFinite(timing.artifactReadyTimeoutMs) ? Math.max(1_000, Math.min(300_000, Number(timing.artifactReadyTimeoutMs))) : 60_000; const deadline = root.performance.now() + timeout; let last = null;
      while (root.performance.now() < deadline) { try { last = adapter.resolveArtifact({ turn_id: artifact.turn_id, index: artifact.index }); if (last?.ready === true) return last; } catch (error) { if (error?.code !== "ARTIFACT_NOT_FOUND") throw error; } await bridge.sleep(timing.pollIntervalMs); }
      throw bridge.error("ARTIFACT_NOT_READY", last ? "Artifact 尚未就绪" : "在限定时间内未找到指定 Artifact", true);
    }
    async function sendArtifactChunks(artifact, requestId) {
      const resolved = await waitForArtifact(artifact); const source = resolved?._source || resolved?.source || artifact?.source || artifact?._source; if (!source || typeof root.fetch !== "function") throw bridge.error("ARTIFACT_UNAVAILABLE", "Artifact 来源不可用"); let response;
      try { response = await root.fetch(source); } catch (error) { throw bridge.error("ARTIFACT_TRANSFER_FAILED", error?.message || "无法读取 Artifact"); }
      if (!response?.ok) throw bridge.error("ARTIFACT_TRANSFER_FAILED", "无法读取 Artifact"); const buffer = await response.arrayBuffer(); const bytes = new Uint8Array(buffer); const mimeType = response.headers?.get?.("content-type") || resolved?.mime_type || artifact?.mime_type || ""; const chunkSize = 256 * 1024;
      const send = async (message) => { const result = chrome.runtime.sendMessage({ ...message, request_id: requestId }); await result?.catch?.(() => {}); };
      await send({ type: "artifact_start", artifact_id: artifact?.id || "", mime_type: mimeType, size: bytes.byteLength });
      for (let offset = 0, sequence = 0; offset < bytes.length; offset += chunkSize, sequence += 1) { let binary = ""; for (const value of bytes.subarray(offset, Math.min(bytes.length, offset + chunkSize))) binary += String.fromCharCode(value); await send({ type: "artifact_chunk", artifact_id: artifact?.id || "", sequence, data: root.btoa(binary) }); }
      await send({ type: "artifact_end", artifact_id: artifact?.id || "" });
      return { transferred: true, size: bytes.byteLength, mime_type: mimeType, _source: source, _source_kind: resolved?._source_kind || artifact?._source_kind || "" };
    }
    async function chat(text, requestId) {
      if (typeof text !== "string" || !text.trim()) throw bridge.error("INPUT_FAILED", "消息不能为空");
      const beforeUsers = adapter.getUsers().length; const baseline = adapter.getLastAssistant(); const started = root.performance.now();
      progress(requestId, "working", started, started);
      await sendText(text); await waitForSubmitted(beforeUsers, baseline, requestId, started); progress(requestId, "submitted", started, started); return await waitForComplete(requestId, baseline, started);
    }
    function observe() { if (!document.body) return; new MutationObserver((records) => { if (records.some((record) => [...record.addedNodes, ...record.removedNodes, record.target].some((node) => adapter.isActivitySubtree(node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement)))) revision += 1; if (!scheduled) { scheduled = true; root.setTimeout(() => { scheduled = false; history.capture({ prepend: history.active }); }, 100); } }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true }); }
    observe();
    return { async handle(message) { if (message.method === "ping") return { ready: true, provider: provider.id }; if (message.method === "get_messages") return history.collect({ limit: message.limit, full: message.full === true }); if (message.method === "chat") return chat(message.text, message.request_id); if (message.method === "get_artifact") return sendArtifactChunks(message.artifact, message.request_id); throw bridge.error("INTERNAL_ERROR", `未知内容脚本方法：${message.method}`); } };
  };
})(globalThis);
