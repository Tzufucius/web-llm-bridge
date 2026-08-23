const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");

function image(attrs = {}, ready = true) {
  const node = new FakeNode("img", attrs);
  node.tagName = "IMG";
  node.complete = ready;
  node.naturalWidth = ready ? 320 : 0;
  node.naturalHeight = ready ? 200 : 0;
  node.currentSrc = attrs.src || "https://cdn.example/generated.png";
  return node;
}

async function run() {
  const users = [];
  const assistants = [new FakeNode("assistant", { "data-message-author-role": "assistant", "data-turn-id": "old" }, "旧回复")];
  let generating = false;
  let answerImage;
  const prompt = new FakeNode("prompt");
  const button = new FakeNode("button");
  const body = new FakeNode("body");
  button.click = () => {
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "生成图片"));
    generating = true;
    const assistant = new FakeNode("assistant", { "data-message-author-role": "assistant", "data-turn-id": "new" }, "");
    answerImage = image({ alt: "generated", src: "data:image/png;base64,ZmFrZQ==" }, false);
    assistant.querySelectorAll = (selector) => selector === "img" ? [answerImage] : [];
    assistants.push(assistant);
    setTimeout(() => { generating = false; }, 20);
    setTimeout(() => { answerImage.complete = true; answerImage.naturalWidth = 320; answerImage.naturalHeight = 200; }, 70);
  };
  const all = () => [body, prompt, button, ...(generating ? [new FakeNode("stop", { "data-testid": "stop-button" })] : []), ...users, ...assistants];
  const document = {
    body,
    scrollingElement: body,
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      if (selector.includes('="user"')) return users;
      if (selector.includes('="assistant"')) return assistants;
      return all().filter((node) => node.matches(selector));
    },
    execCommand: () => false,
  };
  const { context, listeners } = loadContentRuntime({ document, timingOverrides: { stableTimeMs: 20, completionConfirmationMs: 40, responseIdleTimeoutMs: 400 } });

  const snapshot = await new Promise((resolve) => listeners[0]({ method: "debug_snapshot" }, {}, resolve));
  assert.equal(snapshot.ok, true);
  assert.equal(snapshot.result.snapshot.assistant.text_length, 3);
  assert.equal(JSON.stringify(snapshot).includes("ZmFrZQ=="), false);

  const response = await new Promise((resolve) => listeners[0]({ method: "chat", text: "生成图片", request_id: "debug-request" }, {}, resolve));
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "");
  assert.equal(response.result.artifacts.length, 1);
  const artifact = response.result.artifacts[0];
  assert.equal(artifact.ready, true);

  const trace = await new Promise((resolve) => listeners[0]({ method: "debug_trace", request_id: "debug-request" }, {}, resolve));
  assert.equal(trace.ok, true);
  const phases = trace.result.trace.events.map((event) => event.phase);
  for (const phase of ["before_send", "submitted", "assistant_node_seen", "artifact_seen", "artifact_ready", "completion_candidate", "completed"]) assert.ok(phases.includes(phase), phase);

  const wait = await new Promise((resolve) => listeners[0]({ method: "wait_artifact", artifact_id: artifact.id, turn_id: artifact.turn_id, index: artifact.index, timeout_ms: 1_000 }, {}, resolve));
  assert.equal(wait.ok, true);
  assert.equal(wait.result.ready, true);
  assert.equal(context.WebLLMBridge.ChatGPTAdapter.getArtifacts(assistants[1])[0].ready, true);
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
