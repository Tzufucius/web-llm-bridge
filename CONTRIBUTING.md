# Contributing to Web LLM Bridge

**English** | [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for helping improve Web LLM Bridge. This project is a local bridge
between a browser page that the user has already authenticated and local CLI or
agent processes. It is not a general LLM gateway, a browser-login tool, or a
remote proxy.

## Ways to contribute

- Report a reproducible bug or a documentation defect without sharing private
  conversation data.
- Improve Python broker, session, transport, protocol, CLI, or test coverage.
- Improve the Manifest V3 extension's shared runtime or the supported ChatGPT
  adapter.
- Add or validate a provider only after confirming that the site's terms and
  the user's explicit authorization permit the work.
- Improve examples, architecture, protocol, provider, and directory documents.

The currently runnable provider is ChatGPT Web. Other providers named in the
README are plans or experiments, not supported integrations.

## Development setup

Use Python 3.11 or later and a supported Node.js runtime for extension smoke
tests:

```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m venv .venv
```

Activate `.venv` with `.venv\Scripts\Activate.ps1` on Windows PowerShell or
`source .venv/bin/activate` on Linux and macOS, then install the project:

```console
python -m pip install -U pip
python -m pip install -e .
```

Load `extension/` as an unpacked extension in Chrome or Edge only when doing a
manual browser check. Complete any site authentication yourself in that browser
profile. The project must never receive or automate credentials.

Before changing an unfamiliar area, read its nearest `README.md`, then consult
the following documents:

- [Architecture](docs/architecture.md) for process ownership and dependency direction.
- [Protocol](docs/protocol.md) for Extension WebSocket and Broker NDJSON contracts.
- [Provider development](docs/provider-development.md) for the Adapter Contract.

## Architecture boundaries

The intended request path is:

```text
CLI / local agent -> Client -> Broker -> Session Manager -> Transport -> Extension adapter -> page DOM
```

- CLI code must use the Broker protocol and must not access the Extension directly.
- The Broker owns the sole Extension WebSocket, session serialization, stable
  errors, and metadata-only session persistence. It listens on loopback by
  default and is not a remote service.
- A Python provider contains only immutable metadata, URL normalization, hosts,
  and capabilities. It must not own a transport, parse DOM, hold selectors, or
  contain authentication state.
- The extension adapter owns site-specific selectors, DOM input and submission,
  page activity, completion, turn identity, history scrolling, and serialization.
- `SessionStore` stores only recovery metadata. It must not persist prompts,
  response bodies, cookies, tokens, passwords, or complete conversation history.

Do not reverse these dependencies merely to make a small change convenient.

## Where to make changes

| Change | Primary location | Required companion work |
| --- | --- | --- |
| Public Python API, errors, or NDJSON schema | `web_llm_bridge/`, `docs/protocol.md` | Update focused protocol/broker tests. |
| Broker request lifecycle or locking | `web_llm_bridge/broker/`, `web_llm_bridge/session/` | Cover ordering, errors, recovery, and concurrency. |
| CLI behavior | `web_llm_bridge/cli/`, `scripts/` | Preserve Broker boundary and update CLI tests/examples. |
| Site-neutral provider metadata | `web_llm_bridge/providers/` | Add URL/capability tests and registry coverage. |
| Site DOM behavior | `extension/providers/<provider>/` | Keep selectors and serializers browser-side; add smoke fixtures. |
| Shared extension runtime or routing | `extension/core/`, `extension/service_worker.js`, `extension/content.js` | Run applicable provider smoke tests. |
| Documentation or examples | closest directory `README.md`, `docs/`, or `examples/` | Keep English and Chinese contribution guides aligned. |

Every directory already has a `README.md` explaining its responsibility. Update
that local document when a change alters the directory's purpose or contract.

## Invariants

Contributions must preserve these properties:

- Authentication stays in the user's already authenticated browser session;
  never read cookies, local storage, tokens, passwords, password fields,
  DevTools/CDP data, private APIs, or the system clipboard.
- Do not add Playwright, Selenium, CDP, private Provider APIs, CAPTCHA bypasses,
  or quota and access-limit bypasses.
- Broker and agent endpoints remain loopback-only by default. Do not turn the
  bridge into an internet-facing service.
- Session registry data remains metadata-only; deleting it must not affect
  browser conversations.
- A Python provider remains DOM-free and site-neutral; the extension adapter is
  the only layer that knows a site's DOM implementation.
- One Broker owns one Extension transport. Same-session operations are
  serialized, and progress events are not final RPC responses.
- A click is not proof of a submitted prompt. A response is not complete until
  the adapter has positive completion evidence and a final confirmation.
- When submission state is uncertain, `chat` must not automatically resend the
  original prompt. Fail with a structured error instead.
- Errors, timeouts, closed sessions, and unavailable extensions must produce
  structured failures, never a partial success.

## Privacy and sensitive data

Do not put any of the following in source, tests, fixtures, examples,
documentation, issues, logs, screenshots, recordings, commits, or pull requests:

- Cookies, access tokens, passwords, API keys, PATs, private keys, or `.env` values.
- Real Conversation URLs, session IDs, browser profile data, prompts, assistant
  responses, screenshots of private chats, or complete chat history.
- User-identifying data, including names, email addresses, organization data,
  attachments, or data copied from browser storage or the clipboard.

Use synthetic hosts, opaque placeholder IDs, and invented fixture text. Treat
the runtime directory and local session registry as sensitive local state.

## Adding a provider

1. Read [Provider development](docs/provider-development.md), understand the
   Adapter Contract, confirm the target site permits the intended automation,
   and obtain the user's explicit authorization. Do not design a credential or
   access-control bypass.
2. Add a minimal immutable `ProviderDefinition` with a unique ID, HTTPS default
   URL, allowed hosts, capabilities, and deterministic URL normalization.
3. Register it without creating another `ExtensionTransport` or embedding DOM
   selectors in Python.
4. Implement its extension profile and adapter. Keep prompt discovery, send,
   submission detection, activity, completion, message extraction, stable turn
   identity, history scrolling, and special serialization in that adapter.
5. Test Python metadata and URL handling with fake transport. Test DOM behavior
   with synthetic fixtures, including page-not-ready, failed submission,
   streaming, tool activity, final confirmation, timeout, virtualized history,
   and serializer fallbacks.
6. Add Provider documentation and update the supported-provider table,
   capability, protocol, directory, and security-boundary docs.
   A provider in a private submodule must be pinned reproducibly; Git credentials
   remain in Git configuration, never in project files.
7. Run a minimal manual smoke check in a real browser only with a user-approved,
   already-authenticated session. Report browser version and DOM assumptions
   without recording private content.

## Tests and browser report

Run the repository's regression commands from the repository root:

```console
python -m pytest
python -m compileall web_llm_bridge
node tests/providers/chatgpt/streaming_completion_smoke.js
node tests/providers/chatgpt/submission_wait_smoke.js
node tests/providers/chatgpt/tool_activity_smoke.js
```

Run focused tests while iterating, then run the complete Python suite and all
applicable `tests/providers/chatgpt/*_smoke.js` scripts before submitting a
change that affects shared behavior. Add a regression test for every bug fix
when the behavior can be reproduced deterministically.

Current baseline, recorded 2026-08-22 on Windows: `python -m pytest` passed
25 tests with Python 3.13.1 and pytest 8.4.2. The eight ChatGPT extension smoke
scripts passed with Node.js v24.14.0: history, isolation, registry, serializer,
streaming completion, submission wait, tabs, and tool activity. These are
synthetic DOM/runtime checks, not a real authenticated-browser end-to-end test.
Real-login E2E remains manual and must not capture private conversation data.
For changes to DOM selectors, sending, streaming, completion, history, or
serialization, report the Chrome or Edge version and explicitly record the
manual browser result as `PASS` or `NOT RUN`.

## Changes and review

Keep changes focused, document changed behavior, and include the commands you
actually ran and their results in the pull request. Use Conventional Commits:

```text
type(scope): imperative summary
```

Use a suitable type such as `feat`, `fix`, `docs`, `test`, `refactor`, `perf`,
`build`, `ci`, `chore`, or `revert`. Keep a commit to one logical topic. Do not
mix unrelated formatting, renaming, generated files, or refactors into a
feature or fix.

Examples:

```text
fix(chatgpt): update response completion detection
docs(readme): clarify persistent session model
test(chatgpt): cover tool activity updates
```

Use an imperative, concise subject with no trailing period.

## License

By submitting a contribution, you license that contribution under
**AGPL-3.0-only**, the license of this repository. No contributor license
agreement or separate contribution template is required.
