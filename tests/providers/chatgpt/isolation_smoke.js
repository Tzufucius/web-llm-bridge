const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../../..");
const core = fs.readdirSync(path.join(root, "extension", "core")).filter((file) => file.endsWith(".js"));
for (const file of core) {
  const source = fs.readFileSync(path.join(root, "extension", "core", file), "utf8");
  assert.equal(/chatgpt\.com|#prompt-textarea|data-message-author-role/i.test(source), false, `${file} 泄漏 Provider 规则`);
}
