#!/usr/bin/env bash
# install.sh — one-command setup for the agentrouter toolkit.
#
#   ./install.sh            install guard (systemd user timer) + verify layers
#
# Idempotent: safe to run repeatedly. Requires systemd user session (Linux).
set -euo pipefail

PRODUCT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "── agentrouter-toolkit installer ─────────────────────────────"
echo "   product root : $PRODUCT_ROOT"
echo "   hermes home  : $HERMES_HOME"
echo ""

# 1) sanity
[ -d "$HERMES_HOME/hermes-agent/.git" ] || {
    echo "✗ hermes-agent repo not found at $HERMES_HOME/hermes-agent"; exit 1; }
command -v systemctl >/dev/null || { echo "✗ systemd not available"; exit 1; }

# 2) install systemd units + guard script
mkdir -p "$SYSTEMD_DIR"
install -m 755 "$PRODUCT_ROOT/scripts/agentrouter-guard.sh" "$SYSTEMD_DIR/agentrouter-guard.sh"
install -m 644 "$PRODUCT_ROOT/systemd/agentrouter-guard.service" "$SYSTEMD_DIR/"
install -m 644 "$PRODUCT_ROOT/systemd/agentrouter-guard.timer" "$SYSTEMD_DIR/"
# point the installed copies at the product root they were installed from
sed -i "s|^PRODUCT_ROOT=.*|PRODUCT_ROOT=\"$PRODUCT_ROOT\"|" "$SYSTEMD_DIR/agentrouter-guard.sh"
sed -i "s|^ExecStart=.*|ExecStart=$PRODUCT_ROOT/scripts/agentrouter-guard.sh|" "$SYSTEMD_DIR/agentrouter-guard.service"
systemctl --user daemon-reload
systemctl --user enable --now agentrouter-guard.timer >/dev/null 2>&1 || true
echo "✓ guard timer installed and enabled (every 10 min + at login)"

# 3) restore any missing layers right now (uses skill-asset sources)
echo ""
python3 "$PRODUCT_ROOT/scripts/restore_agentrouter_layers.py" --apply || true

# 4) authoritative check
if python3 "$PRODUCT_ROOT/scripts/restore_agentrouter_layers.py" --check | tail -1 | grep -q "all agentrouter layers present"; then
    echo "✓ all code layers present in $HERMES_HOME/hermes-agent"
else
    echo "✗ some layers still missing — see output above"; exit 1
fi

# 5) run regression tests if the repo venv exists
VENV_PY=""
for v in .venv venv; do
    [ -x "$HERMES_HOME/hermes-agent/$v/bin/python" ] && VENV_PY="$HERMES_HOME/hermes-agent/$v/bin/python" && break
done
if [ -n "$VENV_PY" ]; then
    echo "✓ running regression tests…"
    (cd "$HERMES_HOME/hermes-agent" && scripts/run_tests.sh \
        tests/agent/test_agentrouter_filter_defang.py \
        tests/run_agent/test_agentrouter_null_stream_chunk.py 2>&1 | grep -E "^=== Summary" ) \
        || { echo "✗ tests failed"; exit 1; }
fi

echo ""
echo "── done. the contract is live ────────────────────────────────"
systemctl --user list-timers agentrouter-guard.timer --no-pager | sed -n '1,2p'
