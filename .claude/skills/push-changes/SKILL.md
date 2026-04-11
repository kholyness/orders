---
name: push-changes
description: Use when the user asks to commit and push changes, push to remote, or save changes to git
---

# Push Changes

When the user asks to push (commit and push) changes, dispatch a subagent on the **haiku** model with clean context to handle it.

## What to do

Dispatch a subagent using the Agent tool with:
- `model: "haiku"`
- The prompt below (fill in the working directory)

```
Working directory: <absolute path>

Task:
1. Run `git status` and `git diff` to see all uncommitted changes.
2. Based on the diff, write a concise commit message in Russian (imperative mood, 1 line, up to 72 chars). Add a blank line, then `Co-Authored-By: Claude Haiku <noreply@anthropic.com>`.
3. Stage all changed files with `git add -A`.
4. Commit with that message.
5. Run `git push`.
6. Report: what was committed and whether the push succeeded.

Rules:
- Do NOT ask for confirmation — just commit and push.
- Do NOT create new files.
- If there is nothing to commit, report that and stop.
```

## Commit message style

Messages should be in Russian, imperative mood — e.g. "добавить фото через Google Drive", "исправить ошибку авторизации", "обновить список моделей".
