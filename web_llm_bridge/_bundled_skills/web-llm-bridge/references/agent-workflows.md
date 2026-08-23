# Agent Workflows

Use the Bridge for a bounded external consultation, not as an automatic step
in every local task.

Useful cases include:

- independent implementation or code review;
- a second opinion on a non-trivial decision;
- cross-model comparison or verification;
- delegated bounded analysis;
- continuing an existing Web LLM Conversation.

## Prompt Construction

The local Agent chooses the context to share and should send a self-contained
Prompt, preferably through stdin:

```text
Task:
What we are working on.

Goal:
What a useful answer should accomplish.

Constraints:
Compatibility, scope, and safety requirements.

Current implementation or conclusion:
The approach already taken and its assumptions.

Relevant evidence:
Only the code, diff, logs, or data needed for this question.

Questions:
1. What should be checked independently?
2. What risks or alternatives matter?
```

The Web LLM cannot see the local repository, terminal, files, git diff, or
hidden reasoning unless the local Agent explicitly includes that information.
Ask for independent assessment rather than confirmation of an existing
conclusion.

## Validate the Result

Treat the Web LLM response as external analysis, not authoritative truth:

```text
Local Agent selects a bounded question
  -> prepares relevant context
  -> calls web-llm-agent
  -> receives external analysis
  -> validates it against code, tests, docs, and primary evidence
  -> decides what to integrate
```

Do not modify code merely because the Web LLM suggested it.

For image replies, treat `result.artifacts` as descriptors only. Materialize a
specific image with:

```bash
web-llm-agent get-artifact --id ARTIFACT_ID --json
```

The Bridge handles HTTPS, `data:`, and `blob:` sources. The Agent must not
inspect provider DOM or pass arbitrary URLs. After `close-session`, a required
Artifact may be temporarily resolved and the bound Tab is closed again; after
`forget-session`, only already materialized files remain guaranteed.
