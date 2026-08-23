const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");

function image(attrs = {}, ready = true) {
  const node = new FakeNode("img", attrs);
  node.tagName = "IMG";
  node.complete = ready;
  node.naturalWidth = ready ? 256 : 0;
  node.naturalHeight = ready ? 256 : 0;
  node.currentSrc = attrs.src || "https://cdn.example/image.png";
  return node;
}

async function run() {
  const users = [];
  const assistants = [];
  let generating = false;
  let answerImage;
  const prompt = new FakeNode("prompt");
  const button = new FakeNode("button");
  const stop = new FakeNode("stop", { "data-testid": "stop-button" });
  const body = new FakeNode("body");
  button.click = () => {
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "生成图片"));
    generating = true;
    const assistant = new FakeNode("assistant", { "data-message-author-role": "assistant", "data-turn-id": "turn-image" }, "");
    const avatar = image({ alt: "avatar", src: "https://cdn.example/avatar.png" });
    answerImage = image({ alt: "generated image", srcset: "https://cdn.example/generated-small.png 1x, https://cdn.example/generated-large.png 2x", src: "https://cdn.example/generated.png" }, false);
    avatar.parentElement = assistant; answerImage.parentElement = assistant;
    assistant.querySelectorAll = (selector) => selector === "img" ? [avatar, answerImage] : [];
    assistants.push(assistant);
    setTimeout(() => { generating = false; }, 20);
    setTimeout(() => { answerImage.complete = true; answerImage.naturalWidth = 256; answerImage.naturalHeight = 256; }, 70);
  };
  const all = () => [body, prompt, button, ...(generating ? [stop] : []), ...users, ...assistants];
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
  const transferEvents = [];
  const { context, listeners } = loadContentRuntime({ document, progress: transferEvents, timingOverrides: { stableTimeMs: 20, completionConfirmationMs: 40, responseIdleTimeoutMs: 400 } });
  const response = await new Promise((resolve) => listeners[0]({ method: "chat", text: "生成图片", request_id: "artifact" }, {}, resolve));
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "");
  assert.equal(response.result.artifacts.length, 1);
  assert.equal(response.result.artifacts[0].kind, "image");
  assert.equal(response.result.artifacts[0].turn_id, "turn-image");
  assert.equal(response.result.artifacts[0]._source, "https://cdn.example/generated-large.png");
  assert.equal("id" in response.result.artifacts[0], false);
  const bytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
  context.btoa = (binary) => Buffer.from(binary, "binary").toString("base64");
  context.fetch = async () => ({ ok: true, headers: { get: () => "image/png" }, arrayBuffer: async () => bytes.buffer });
  const artifact = { id: "img_test", ...response.result.artifacts[0] };
  const transfer = await new Promise((resolve) => listeners[0]({ method: "get_artifact", request_id: "transfer", artifact }, {}, resolve));
  assert.equal(transfer.ok, true);
  assert.equal(transfer.result.transferred, true);
  assert.ok(transferEvents.some((event) => event.type === "artifact_start"));
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
