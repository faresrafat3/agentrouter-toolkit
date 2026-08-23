# agentrouter-toolkit

**Self-healing agentrouter.org compatibility for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Run claude-opus-5, gpt-5.6-sol, and claude-opus-4-8 through [agentrouter.org](https://agentrouter.org) — reliably, on every profile, surviving every update.

## Why This Exists

agentrouter.org fronts frontier models for free/cheap, but applies four deterministic quirks that break stock Hermes:

| # | Symptom | Root Cause |
|---|---------|-----------|
| A | `HTTP 500 sensitive_words_detected` | substring blocklist — one word anywhere in a 100 KB prompt kills the request |
| B | `HTTP 400 content-blocked` | short-input / language classifier |
| C | Stream dies mid-answer (`'NoneType' has no attribute 'choices'`) | gateway emits literal `data: null` SSE frames |
| D | `HTTP 401 unauthorized_client` with a valid key | every request must carry `User-Agent: claude-cli/1.0.0 (external, cli)` |

These fixes live as **local compatibility layers** in the Hermes working tree.
Every `hermes update` (terminal autostash or desktop `--keep-stash`) wipes them.

This toolkit ships the fixes **plus a self-healing guard** that detects each wipe
and re-applies from its own assets — no git stashes required, no manual intervention.

## Quick Start

```bash
git clone https://github.com/faresrafat3/agentrouter-toolkit.git
cd agentrouter-toolkit
./install.sh
```

One command does everything:
1. Installs the guard as a systemd **user** timer (every 10 min + at login)
2. Restores any missing compatibility layers immediately
3. Verifies all layers are present
4. Runs the full regression suite

Requires Linux with a systemd user session. Override install path: `HERMES_HOME=/path ./install.sh`

## What Gets Protected

| Layer | What It Does |
|-------|-------------|
| Sanitizer gate | Rewrites filter-trigger words + hyphen defang, keyed by wire target (name OR base URL) |
| Null-chunk guard | Skips `data: null` SSE frames instead of crashing the stream |
| Payload dumper | Flag-file debug capture (`touch /tmp/ar_dump_on` → `/tmp/ar_payloads.jsonl`) |
| Credits gate | Suppresses false "Credit access paused" banner on non-Nous targets |
| INF timeouts | Disables stale/request watchdogs for slow reasoning models |
| Self-healing guard | Detects wipes every 10 min; re-applies from this repo's own assets |
| Regression tests | 10 behavior-based tests, restored into Hermes repo by the guard |

## Per-Profile Setup

The code layers are shared across all profiles automatically. For each profile's config:

```bash
hermes profile create <name> --clone   # copies config.yaml + .env from source
```

Or set manually — each profile needs:

```yaml
providers:
  agentrouter-1:
    name: agentrouter-1
    base_url: https://agentrouter.org/v1
    key_env: AGENTROUTER_KEY_1
    stale_timeout_seconds: inf     # no watchdog on slow reasoning models
    request_timeout_seconds: inf   # no socket-level kill either
    extra_headers:
      User-Agent: claude-cli/1.0.0 (external, cli)
    models:
      claude-opus-5: {}
      gpt-5.6-sol: {}
      claude-opus-4-8: {}
```

And `AGENTROUTER_KEY_1` in that profile's `.env`.

## Health Check

```bash
python3 scripts/restore_agentrouter_layers.py --check
systemctl --user list-timers agentrouter-guard.timer
hermes agentrouter status   # if plugin is symlinked
```

All green = the contract holds.

## Architecture

```
scripts/
  restore_agentrouter_layers.py   --check | --apply   idempotent core engine
  agentrouter-guard.sh            what the timer runs every 10 min
assets/
  message_sanitizer_block.txt     canonical sanitizer source-of-truth
  test_agentrouter_*.py           regression tests (copied into Hermes repo)
systemd/                          user units installed by install.sh
plugin.yaml + __init__.py         Hermes visibility plugin (`hermes agentrouter status`)
references/product-contract-v0.md the full specification
SKILL.md                          same content as a Hermes skill
```

## Provenance

Production v0. Live-verified on a real multi-profile Hermes host (2026-08-22):
simulated update-wipe → auto-restored in one guard tick; 100 regression tests
green across 5 test files; wire-target gate proven against a live HTTP 400
content-blocked incident; peer-audited with 7 findings (all resolved).

## License

MIT
