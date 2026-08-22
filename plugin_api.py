"""agentrouter-toolkit — Hermes plugin surface.

Read-only visibility + convenience. The actual healing is done by the
systemd user guard (installed via install.sh); this plugin NEVER mutates
core files (policy: plugins must not touch core). It exposes:

    hermes agentrouter status   — layers / guard / fallback / last-heal

Install (as a user plugin):
    ln -s ~/Projects/agentrouter-toolkit ~/.hermes/plugins/agentrouter-toolkit
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
REPO = HERMES_HOME / "hermes-agent"
STATE_DIR = Path(
    os.environ.get("AGENTROUTER_GUARD_STATE")
    or os.environ.get("XDG_STATE_HOME")
    or Path.home() / ".local" / "state"
) / "agentrouter-guard"
LOG = STATE_DIR / "guard.log"


def _layers_ok() -> tuple[bool, str]:
    script = PRODUCT_ROOT / "scripts" / "restore_agentrouter_layers.py"
    if not script.exists():
        return False, "restore script missing"
    try:
        out = subprocess.run(
            ["python3", str(script), "--check"],
            capture_output=True, text=True, timeout=60,
        )
        ok = "all agentrouter layers present" in out.stdout
        return ok, out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[:120]
    except Exception as exc:
        return False, f"check failed: {exc}"


def _guard_info() -> str:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-active", "agentrouter-guard.timer"],
            capture_output=True, text=True, timeout=10,
        )
        state = out.stdout.strip() or "unknown"
    except Exception:
        state = "systemctl unavailable"
    last = "no heals yet"
    if LOG.exists():
        try:
            lines = [
                ln for ln in LOG.read_text(encoding="utf-8").splitlines()
                if "layers missing" in ln or "VERIFIED" in ln
            ]
            if lines:
                last = lines[-1][:100]
        except Exception:
            pass
    return f"timer: {state} | last event: {last}"


def _fallback_info() -> str:
    cfg = HERMES_HOME / "config.yaml"
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        chain = data.get("fallback_providers") or []
        if chain:
            first = chain[0]
            return f"armed: {first.get('model')} via {first.get('provider')}"
        return "NOT armed — stalls will surface as empty replies (run: hermes fallback add)"
    except Exception as exc:
        return f"unreadable: {exc}"


def status_text() -> str:
    ok, detail = _layers_ok()
    lines = [
        "agentrouter-toolkit status",
        f"  layers  : {'✓ present' if ok else '✗ MISSING'} ({detail})",
        f"  guard   : {_guard_info()}",
        f"  fallback: {_fallback_info()}",
        f"  checked : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines)


def register_cli(subparser) -> None:
    """Wire `hermes agentrouter` (status only — healing stays with the guard)."""
    p = subparser.add_parser(
        "agentrouter",
        help="agentrouter-toolkit: show compatibility-layer status",
    )
    sub = p.add_subparsers(dest="agentrouter_cmd")
    sub.add_parser("status", help="layers / guard / fallback summary")

    def _run(args):
        print(status_text())
        return 0

    p.set_defaults(func=_run)


def register(ctx) -> None:
    """Plugin entry point. Visibility only — no core mutation."""
    try:
        ctx.register_cli_command("agentrouter", register_cli)
    except Exception:
        pass  # CLI registration is best-effort; status_text stays importable
