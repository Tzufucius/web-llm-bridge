const assert = require("node:assert/strict");
const { FakeNode, loadContentRuntime } = require("./helpers");

async function run() {
  const users = [];
  const assistants = [new FakeNode("assistant", { "data-message-author-role": "assistant", "data-turn-id": "old" }, "old answer")];
  let prompt;
  const button = new FakeNode("button");
  const body = new FakeNode("body");
  button.click = () => {
    users.push(new FakeNode("user", { "data-message-author-role": "user" }, "new prompt"));
    setTimeout(() => assistants.push(new FakeNode("assistant", { "data-message-author-role": "assistant", "data-turn-id": "new" }, "new answer")), 80);
  };
  const document = {
    body,
    scrollingElement: body,
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      if (selector.includes('="user"')) return users;
      if (selector.includes('="assistant"')) return assistants;
      if (selector.includes('="send-button"') || selector.includes('composer-submit-button')) return [button];
      if (selector.includes("prompt-textarea")) return prompt ? [prompt] : [];
      return [];
    },
    execCommand: () => false,
  };
  prompt = new FakeNode("prompt");
  prompt.value = "";
  prompt.isContentEditable = false;
  const { listeners } = loadContentRuntime({ document, timingOverrides: { stableTimeMs: 10, completionConfirmationMs: 20, pollIntervalMs: 5, responseIdleTimeoutMs: 300 } });
  const response = await new Promise((resolve) => listeners[0]({ method: "chat", text: "new prompt", request_id: "stale" }, {}, resolve));
  assert.equal(response.ok, true);
  assert.equal(response.result.text, "new answer");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
