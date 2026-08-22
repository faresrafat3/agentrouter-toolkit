"""agentrouter-toolkit — Hermes plugin visible surface.

Read-only visibility: ``hermes agentrouter status``. Never mutates core
files (policy: plugins must not touch core). The healing itself is done
by the systemd user guard installed via install.sh.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
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
        last = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[:120]
        return ok, last
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
            events = [
                ln for ln in LOG.read_text(encoding="utf-8").splitlines()
                if "layers missing" in ln or "VERIFIED" in ln
            ]
            if events:
                last = events[-1][:100]
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
        return "NOT armed — stalls surface as empty replies (run: hermes fallback add)"
    except Exception as exc:
        return f"unreadable: {exc}"


def status_text() -> str:
    ok, detail = _layers_ok()
    return "\n".join([
        "agentrouter-toolkit status",
        f"  layers  : {'✓ present' if ok else '✗ MISSING'} ({detail})",
        f"  guard   : {_guard_info()}",
        f"  fallback: {_fallback_info()}",
        f"  checked : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ])


def register_cli(subparser) -> None:
    """setup_fn for the plugin CLI contract.

    The core passes the ``agentrouter`` subparser itself (already created
    from register_cli_command's name), so attach the ``status`` subcommand
    via its own add_subparsers.
    """
    sub = subparser.add_subparsers(dest="agentrouter_cmd")
    p = sub.add_parser(
        "status",
        help="agentrouter compatibility layers / guard / fallback summary",
    )
    p.set_defaults(_agentrouter_status=True)


def handle_status(args) -> int:
    """handler_fn: print the status report."""
    print(status_text())
    return 0


def register(ctx) -> None:
    """Plugin entry point. Visibility only — never mutates core files.

    Real core signature (hermes_cli/plugins.py):
        register_cli_command(name, help, setup_fn, handler_fn=None, description="")
    """
    try:
        ctx.register_cli_command(
            "agentrouter",
            "agentrouter compatibility layers status",
            register_cli,
            handler_fn=handle_status,
            description="Show agentrouter-toolkit layer/guard/fallback status",
        )
    except Exception:
        pass  # best-effort: status_text stays importable regardless
