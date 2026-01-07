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
- Be concise: avoid listing changed files or implementation details
- Include brief "why" when it clarifies motivation (e.g., "to fix X", "to improve Y")
- Output must be a single line; no alternatives, no extra text

Examples:
- Good: `refactor(equipment): rename barLength to sleeveLength to clarify sleeve capacity`
- Bad: `refactor: update Barbell and PlateLoadedCable classes to replace barLength with sleeveLength, enhancing clarity in equipment specifications, and adjust related UI components and tests accordingly`

Output format:
Commit message: <type>(<scope>): <summary>