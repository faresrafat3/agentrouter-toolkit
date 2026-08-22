# Verifying the delegate_task -> opus-5 (agentrouter.org) routing

## Why verify
`delegate_task` uses the **default profile model** (not an arg you pass). If the active
session is on a weaker default (e.g. `tencent/hy3:free`), the child will NOT be opus-5
even though the user asked for the stronger model. Always confirm before dispatching.

## How to verify (read-only)
```bash
grep -nE "default:|provider:|base_url:|key_env:" ~/.hermes/config.yaml | head
```
Expected for opus-5 via agentrouter.org:
```
model:
  default: claude-opus-5
  provider: agentrouter-org
  base_url: https://agentrouter.org/v1
  key_env: HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY
```
A transcript head like `Model: claude-opus-5` in the live log confirms the child actually
routed there (not just the config intent).

## Dispatch shape (correct)
```python
delegate_task(
    goal="<self-contained, English, 5-7 bullets, <=280 words>",
    context="<why this matters; short>",
    role="leaf",
)
```
- `hermes` CLI has **NO `delegate` subcommand** — shelling out to `hermes delegate ...`
  errors with the usage dump. Use the agent's own `delegate_task` tool.
- Reachable models on the same provider: `agentrouter-org/claude-opus-5`,
  `agentrouter-org/gpt-5.6-sol`, `agentrouter-org/claude-opus-4-8`.

## Two-key rotation for parallelism (dodge HTTP 429)
Two API keys exist: `HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY` and
`HERMES_CUSTOM_AGENTROUTER_ORG_API_KEY_2`. Add a second `agentrouter-org-2` provider
entry in `config.yaml` (same base_url, `key_env: ..._API_KEY_2`) and dispatch parallel
batches against alternating providers. Always make a backup of `config.yaml` first
(`cp ~/.hermes/config.yaml /tmp/config.yaml.bak`).

## Monitor the child (prevent drift)
Tail: `~/.hermes/cache/delegation/live/<deleg_id>/task-0.log`
On completion, `git -C <repo> status` and diff against the assigned acceptance — a child
may build a DIFFERENT spike than requested (observed: P2 Verified Closure -> prime_agent
ADR-0005). Revert drifted changes: `git restore --staged <f>` + `git checkout -- <f>`, then
re-dispatch with a narrower prompt.
