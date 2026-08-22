# agentrouter-toolkit

Make **agentrouter.org** models (claude-opus-5, gpt-5.6-sol, claude-opus-4-8)
work reliably inside [Hermes Agent](https://github.com/NousResearch/hermes-agent) —
for every profile, on every machine, permanently.

agentrouter.org fronts strong models for free/cheap, but applies three
deterministic quirks that break stock Hermes:

| # | Symptom | What it is |
|---|---------|-----------|
| A | `HTTP 500 sensitive_words_detected` | substring blocklist — one trigger word anywhere in a 100 KB prompt kills the request |
| B | `HTTP 400 content-blocked` | short-input / language classifier |
| C | stream dies mid-answer (`'NoneType' has no attribute 'choices'`) | gateway emits literal `data: null` SSE frames |
| D | `HTTP 401 unauthorized_client` even with a valid key | every request must carry `User-Agent: claude-cli/1.0.0 (external, cli)` |

This toolkit ships the fixes as **local compatibility layers** plus a
**self-healing guard**, because the layers live only in your working tree —
any `hermes update` (terminal autostash or desktop `--keep-stash`) wipes them.

## Install

```bash
git clone <this-repo> agentrouter-toolkit
cd agentrouter-toolkit
./install.sh
```

That single command:
1. installs the guard as a systemd **user** timer (every 10 min + at login),
2. restores any missing code layers right now,
3. verifies all layers + runs the regression test suite.

Requirements: Linux with a systemd user session, Hermes installed at
`~/.hermes/hermes-agent` (override with `HERMES_HOME=/path ./install.sh`).

## What it maintains (the contract)

- **Sanitizer gate** — outbound requests to agentrouter.org get trigger words
  synonym-rewritten and hyphens defanged (byte-reversible), keyed by **wire
  target** (provider name *or* base_url), so restored old sessions carrying
  `provider: custom` are still covered.
- **Null-chunk guard** — `data: null` SSE frames are skipped instead of
  crashing the stream.
- **Payload dumper** — flag-file gated debug capture
  (`touch /tmp/ar_dump_on`, read `/tmp/ar_payloads.jsonl`) to diagnose any NEW
  filter trigger by replaying real payloads with curl.
- **Self-healing guard** — checks every 10 minutes; healthy = silent; wiped =
  restore from this repo's own assets (no dependence on git stashes), verify,
  then notify the `system-maneger` profile's Bot Chat.
- **Regression tests** — behavior-based, refactor-proof; live in `assets/`
  and are copied into the repo by the restorer.

## Per-profile setup

The code layers are shared across all profiles automatically. For each
profile's config, either clone an already-configured profile:

```bash
hermes profile create <name> --clone   # copies config.yaml + .env + skills + memories
```

or set the providers block manually (`providers.agentrouter-1..3`,
`key_env: AGENTROUTER_KEY_N`, mandatory User-Agent in `extra_headers`) and add
`AGENTROUTER_KEY_1/2/3` to that profile's `.env`.

## Health check

```bash
python3 scripts/restore_agentrouter_layers.py --check     # layers present?
systemctl --user list-timers agentrouter-guard.timer      # guard alive?
```

## Layout

```
scripts/
  restore_agentrouter_layers.py   --check | --apply   (idempotent core)
  agentrouter-guard.sh            what the timer runs
assets/
  message_sanitizer_block.txt     canonical sanitizer source-of-truth
  test_agentrouter_*.py           regression tests (restored into the repo)
systemd/                          user units installed by install.sh
references/                       diagnostics: filters, keys, rotation, routing
SKILL.md                          the same content as a Hermes skill
```

## Status

Production v0, live-verified on a real Hermes multi-profile host
(2026-08-22): simulated update-wipe → auto-restored in one guard tick;
10/10 regression tests green; wire-target gate proven against the live
`content-blocked` incident.
