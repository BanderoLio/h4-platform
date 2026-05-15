# OpenCode prompts extract

Source: https://github.com/sst/opencode

Commit: `9975c1ed1ce3517251cd69e52f76a16eb4d2a664`

Extracted on: 2026-05-15

## Contents

- `session/` - model/provider system prompt fragments from `packages/opencode/src/session/prompt/*.txt`.
- `agents/` - native subagent and internal agent prompts from `packages/opencode/src/agent/prompt/*.txt`, plus `generate.txt`.
- `tools/` - built-in tool descriptions/prompts from `packages/opencode/src/tool/*.txt` and `packages/opencode/src/tool/shell/*.txt`.
- `context/agent.ts` - native agent definitions, including `build`, `plan`, `general`, `explore`, optional `scout`, `compaction`, `title`, and `summary`.
- `context/system.ts` - logic that chooses provider-specific prompt fragments and injects environment/skills context.

## Native agents found

- `build` - primary default agent. Executes tools according to configured permissions.
- `plan` - primary planning mode. Denies edit tools except plan files.
- `general` - native subagent for complex research and multi-step work.
- `explore` - native subagent specialized for fast codebase exploration.
- `scout` - experimental native subagent for docs/dependency source research.
- `compaction`, `title`, `summary` - hidden internal primary agents.

The actual prompt text is preserved in the copied `.txt` files.
