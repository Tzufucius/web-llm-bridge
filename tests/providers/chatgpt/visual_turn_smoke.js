const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");

async function run() {
  const users = [];
  const assistants = [];
  const turns = [];
  let generating = false;
  const prompt = new FakeNode("prompt");
  const button = new FakeNode("button");
  const body = new FakeNode("body");
  button.click = () => {
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "生成图片"));
    generating = true;
    const turn = new FakeNode("turn", { "data-turn-id": "visual-only" });
    const image = new FakeNode("img", { alt: "已生成图片：测试", src: "https://chatgpt.com/backend-api/estuary/content?id=file_test" });
    image.tagName = "IMG"; image.complete = false; image.naturalWidth = 0; image.naturalHeight = 0;
    image.parentElement = turn;
    turn.querySelectorAll = (selector) => selector === "img" ? [image] : [];
    turns.push(turn);
    setTimeout(() => { generating = false; image.complete = true; image.naturalWidth = 100; image.naturalHeight = 80; }, 60);
  };
  const document = {
    body,
    scrollingElement: body,
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      if (selector.includes('="user"')) return users;
      if (selector.includes('="assistant"')) return assistants;
      if (selector.includes("[data-turn-id]")) return turns;
      return [body, prompt, button, ...users, ...assistants, ...turns].filter((node) => node.matches(selector));
    },
    execCommand: () => false,
  };
  const { listeners } = loadContentRuntime({ document, timingOverrides: { stableTimeMs: 20, completionConfirmationMs: 40, responseIdleTimeoutMs: 400 } });
  const response = await new Promise((resolve) => listeners[0]({ method: "chat", text: "生成图片", request_id: "visual-only" }, {}, resolve));
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "");
  assert.equal(response.result.artifacts.length, 1);
  assert.equal(response.result.artifacts[0].turn_id, "visual-only");
  assert.equal(response.result.artifacts[0].ready, true);
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
