---
alwaysApply: true
---
## Commit message after summary

After the **Summarization** section (and only then), output exactly **one** Git commit message.

Use **Conventional Commits**:
`<type>(<scope>): <summary>`

Constraints:
- Allowed types: feat|fix|refactor|perf|test|docs|build|ci|chore|revert
- scope is optional; use it only if obvious
- summary: imperative, intent-focused, <= 72 chars, no trailing period
- Output must be a single line; no alternatives, no extra text

Output format:
Commit message: <type>(<scope>): <summary>