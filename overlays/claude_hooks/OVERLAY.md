# claude_hooks

Vendors a curated subset of [karanb192/claude-code-hooks](https://github.com/karanb192/claude-code-hooks)
(MIT, commit `18b77a5`) into the generated service's `.claude/` as **pure checked-in
JavaScript**, and generates `.claude/settings.json` wiring only the hooks the project
selects. D-041.

## Answers

| key | default | effect |
|---|---|---|
| `claude_hooks` | `true` | Master gate. Off = no `.claude/` directory at all. |
| `hook_guard_pack` | `true` | Vendor `hooks/guard-pack.js` + `hooks/lib/{block-dangerous-commands,protect-secrets,git-safety,protect-tests,case-insensitive-guard,config-guard}.js`; wire PreToolUse `Bash\|Read\|Edit\|MultiEdit\|Write`. |
| `hook_format_code` | `true` | Vendor `hooks/format-code.js`; wire PostToolUse `Write\|Edit`. Runs `uv run ruff format` + `ruff check --fix` (same ruff as pre-commit / CI), prettier for non-Python. |
| `hook_protect_tests` | `true` | Vendor `hooks/protect-tests.js` (standalone); wire PreToolUse `Bash\|Edit\|MultiEdit\|Write`. Redundant with guard-pack's bundled copy - harmless together. |
| `hook_auto_stage` | `false` | Vendor `hooks/auto-stage.js`; wire PostToolUse `Edit\|Write`. `git add`s Claude's edits. |
| `hook_session_logger` | `false` | Vendor `hooks/session-logger.js`; wire SessionStart / PostToolUse / SessionEnd. Logs under `~/.claude/sessions/`, not the repo. |
| `hook_instructions_audit` | `false` | Vendor `hooks/instructions-audit.js`; wire InstructionsLoaded / UserPromptSubmit / PreToolUse. |

Each `hook_*` gates **both** the file copy and the `settings.json` entry - an
unselected hook leaves no dead code behind. Toggle via `copier update`, never by
hand-editing `settings.json` (generated).

## Rendered layout (all `hook_*` on)

```
.claude/
  .gitignore              # settings.local.json
  settings.json           # generated, wires the selected hooks
  hooks/
    VENDORED.md           # provenance + upstream MIT license text
    guard-pack.js
    lib/{block-dangerous-commands,protect-secrets,git-safety,protect-tests,case-insensitive-guard,config-guard}.js
    format-code.js
    auto-stage.js
    protect-tests.js
    session-logger.js
    instructions-audit.js
```

## Requirements

- **Node >= 18** on `PATH`. Hooks fail open if node is absent (Claude Code logs and
  continues); they never block a session on their own missing runtime.
- `format-code.js` also uses `uv` (already required) and `npx prettier`.

## Determinism

Pure static file copy + one generated `settings.json` that is a deterministic
function of the `hook_*` answers. No shared-file fragment slots, no post hooks, no
network at render time. Vendored `.js` carries no Jinja tokens, so it renders
byte-identical to upstream. Double-render byte-identical.

## Not covered (BACKLOG / Phase 7)

- The other ~15 upstream hooks (bounty-board, nerf-receipts, standup-autopilot,
  notify-permission/Slack, context-hogs, dead-rules-audit, cache-tax,
  pr-provenance-stamp, dead-end-registry, config-watch, guard-pack's individual
  guards as separate plugins). Add on request.
- Multi-service topology renders a per-service `.claude/`; a single repo-root
  `.claude/` for `monorepo` is a topology root-layer refinement.
- Refreshing the vendored copy when upstream moves is a manual re-vendor + bump of
  the commit SHA in `registry.yaml` / `VENDORED.md`.
