#!/usr/bin/env bash
# agentrouter-guard.sh — keep agentrouter.org compatibility layers alive across updates.
#
# WHY: the agentrouter layers (sanitizer, null-chunk guard, dump hook, wiring)
# are local-only work that does NOT exist in upstream hermes-agent. Any update
# (terminal `hermes update`, desktop app --keep-stash, git reset) wipes them.
# This guard runs from OUTSIDE the repo (systemd user timer) and re-applies
# them via the skill's restore script when missing. Silent when healthy.
#
# Install (systemd user units live in this same directory):
#   cp agentrouter-guard.* ~/.config/systemd/user/
#   systemctl --user daemon-reload
#   systemctl --user enable --now agentrouter-guard.timer

set -u

# Product root = directory containing this script's parent (scripts/..)
PRODUCT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$PRODUCT_ROOT"
RESTORE="$PRODUCT_ROOT/scripts/restore_agentrouter_layers.py"
REPO="${HERMES_HOME:-$HOME/.hermes}/hermes-agent"
# State dir: keep guard state out of the product repo (it may be a git checkout).
# XDG state home by default; overridable.
STATE_DIR="${AGENTROUTER_GUARD_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/agentrouter-guard}"
mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="/tmp/agentrouter-guard"
LOG="$STATE_DIR/guard.log"
LOCK="$STATE_DIR/guard.lock"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Reap stale locks (holder died without cleanup)
if [ -f "$LOCK" ] && ! kill -0 "$(cat "$LOCK")" 2>/dev/null; then
    rm -f "$LOCK"
fi

if [ -f "$LOCK" ]; then
    log "skip: another guard run holds the lock"
    exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 1) Sanity: skill + repo exist
[ -f "$RESTORE" ] || { log "ERROR: restore script missing at $RESTORE"; exit 1; }
[ -d "$REPO/.git" ] || { log "ERROR: repo missing at $REPO"; exit 1; }

# 2) Authoritative check: the skill's own layer checker (single source of truth).
#    Cheap enough for a 10-min timer; silent + rc=0 when all layers present.
CHECK_OUT="$(python3 "$RESTORE" --check 2>&1)"
if echo "$CHECK_OUT" | grep -q "all agentrouter layers present"; then
    exit 0   # all layers present — say nothing, wake nothing
fi

# 3) Layers missing → authoritative check + restore
log "layers missing — running restore"
APPLY_OUT="$(python3 "$RESTORE" --apply 2>&1)"
APPLY_RC=$?
log "restore rc=$APPLY_RC: $(echo "$APPLY_OUT" | tail -3 | tr '\n' ' | ')"

# 4) Restore regression tests: prefer skill assets (behavior-based, refactor-proof);
#    fall back to the pinned upstream commit if assets are gone.
cd "$REPO" || exit 1
T_NULL="tests/run_agent/test_agentrouter_null_stream_chunk.py"
T_DEFANG="tests/agent/test_agentrouter_filter_defang.py"

if [ -f "$SKILL_DIR/assets/test_agentrouter_null_stream_chunk.py" ]; then
    mkdir -p "$(dirname "$T_NULL")" "$(dirname "$T_DEFANG")"
    cp "$SKILL_DIR/assets/test_agentrouter_null_stream_chunk.py" "$T_NULL"
    cp "$SKILL_DIR/assets/test_agentrouter_filter_defang.py" "$T_DEFANG"
    log "tests restored from skill assets"
else
    git checkout a2071f6162 -- "$T_NULL" "$T_DEFANG" 2>/dev/null
    git restore --staged tests/ 2>/dev/null
    log "tests restored from pinned commit a2071f6162"
fi

# 5) Verify with the script's own check
CHECK_OUT="$(python3 "$RESTORE" --check 2>&1)"
if echo "$CHECK_OUT" | grep -q "all agentrouter layers present"; then
    log "VERIFIED: all layers present after restore"
else
    log "WARN: check still failing after restore: $(echo "$CHECK_OUT" | tail -2 | tr '\n' ' ')"
fi

# 6) Ping the desktop app's system-maneger bot chat so Fares knows it healed.
#    Fire-and-forget, quiet-mode; failure here is non-fatal (logged only).
#    Set GUARD_NO_PING=1 to suppress (used by tests).
if command -v hermes >/dev/null 2>&1 && [ "${GUARD_NO_PING:-0}" != "1" ]; then
    (
        HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}" timeout 150 \
        hermes chat --in ~ -c "Bot Chat" --create-if-missing -Q -q "System note from the agentrouter guard: an update wiped the agentrouter compatibility layers from the shared codebase and I just restored them automatically. If your session was mid-request when this happened it may have failed once; retry it now. No action needed from you beyond a retry if something looked stuck."
    ) >> "$LOG" 2>&1 &
    log "notified system-maneger profile"
fi

exit 0
