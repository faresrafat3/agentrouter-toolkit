#!/usr/bin/env python3
"""Check & restore the agentrouter content-filter layers in hermes-agent.

WHY THIS EXISTS (2026-08-22): `hermes update` runs `git reset --hard
origin/main` + autostash, and the desktop updater uses --keep-stash (stash
without re-apply). The agentrouter layers are LOCAL-ONLY work that does not
exist upstream, so every update wipes them from the working tree while the
objects survive in git. The bot-plugin profile (system-maneger) then hits raw
HTTP 500 sensitive_words_detected again.

Usage:
    python3 restore_agentrouter_layers.py --check   # exit 0 = all layers present
    python3 restore_agentrouter_layers.py --apply   # restore whatever is missing

Sources used by --apply, in order:
  stash@{1} (2026-08-14 snapshot, complete layer set)
  stash@{0}, commit a2071f6162, commit ae93183cb2 (fallbacks)
Regression tests are restored from the skill's own assets/ copies first
(behavior-based, refactor-proof), falling back to pinned commit a2071f6162.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Product root = parent of scripts/; repo target resolved from $HERMES_HOME
# (defaults to the standard install path).
PRODUCT_ROOT = Path(__file__).resolve().parent.parent
_hermes_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
REPO = Path(_hermes_home) / "hermes-agent"
HELPERS = REPO / "agent" / "chat_completion_helpers.py"
SANIT = REPO / "agent" / "message_sanitization.py"
TEST_NULL = REPO / "tests" / "run_agent" / "test_agentrouter_null_stream_chunk.py"
TEST_DEFANG = REPO / "tests" / "agent" / "test_agentrouter_filter_defang.py"

SKILL_DIR = PRODUCT_ROOT  # product root doubles as the skill dir
ASSET_NULL = SKILL_DIR / "assets" / "test_agentrouter_null_stream_chunk.py"
ASSET_DEFANG = SKILL_DIR / "assets" / "test_agentrouter_filter_defang.py"

SANITIZER_START = "# agentrouter.org content filters — single owner"
DUMPER_ANCHOR = '_OPENROUTER_PROVIDER_SORT_VALUES = {"throughput", "latency", "price"}'

# (name, probe) — all must hold for --check to pass.
LAYERS = [
    ("sanitizer module", lambda: "def sanitize_for_agentrouter(" in SANIT.read_text(encoding="utf-8")),
    ("helpers import", lambda: "sanitize_for_agentrouter,\n)" in HELPERS.read_text(encoding="utf-8")),
    ("dumper defined", lambda: "def _maybe_dump_agentrouter_payload(" in HELPERS.read_text(encoding="utf-8")),
    ("dispatch site", lambda: re.search(r"def _dispatch_nonstreaming_api_request.*?_maybe_dump_agentrouter_payload\(.*?sanitize_for_agentrouter\(", HELPERS.read_text(encoding="utf-8"), re.DOTALL)),
    ("stream site", lambda: re.search(r"def _open_stream.*?sanitize_for_agentrouter\(", HELPERS.read_text(encoding="utf-8"), re.DOTALL)),
    ("summary site", lambda: re.search(r"# Strip all remaining underscore-prefixed.*?sanitize_for_agentrouter\(\s*api_messages", HELPERS.read_text(encoding="utf-8"), re.DOTALL)),
    ("null-chunk guard", lambda: re.search(r"def _iter_provider_stream_chunks.*?if chunk is None:", HELPERS.read_text(encoding="utf-8"), re.DOTALL)),
    ("regression tests", lambda: TEST_NULL.exists() and "_iter_provider_stream_chunks" in TEST_NULL.read_text(encoding="utf-8")),
]

GIT_SNAPSHOT_SOURCES = ["stash@{1}", "stash@{0}", "a2071f6162", "ae93183cb2"]


def git_show(spec: str, path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{spec}:{path}"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def extract_sanitizer_block(source_text: str) -> str | None:
    si = source_text.find(SANITIZER_START)
    if si == -1:
        return None
    # Block ends at the next top-level section banner after the sanitizer.
    ei = source_text.find("# call_id policy — single owner", si)
    if ei == -1:
        ei = min(len(source_text), si + 8000)
    block = source_text[si:ei].rstrip()
    ok = all(s in block for s in (
        "_SENSITIVE_WORD_REPLACEMENTS", "def _defang_sensitive_words(",
        "def sanitize_for_agentrouter(",
    ))
    return block + "\n" if ok else None


def restore_regression_tests(changed: list[str]) -> None:
    """Put both regression test files back. Skill assets first (they exercise
    behavior and survive refactors); pinned commit as fallback."""
    pairs = [
        (ASSET_NULL, TEST_NULL),
        (ASSET_DEFANG, TEST_DEFANG),
    ]
    for src, dst in pairs:
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copyfile(src, dst)
            changed.append(f"tests:{dst.name}")
        else:
            snap = git_show("a2071f6162", str(dst.relative_to(REPO)))
            if snap is not None:
                dst.write_text(snap, encoding="utf-8")
                changed.append(f"tests:{dst.name}")


def apply() -> int:
    helpers = HELPERS.read_text(encoding="utf-8")
    changed = []

    def replace_first(old: str, new: str) -> bool:
        nonlocal helpers
        if old in helpers:
            helpers = helpers.replace(old, new, 1)
            return True
        return False

    # 1) sanitizer module block
    sanit = SANIT.read_text(encoding="utf-8")
    if "def sanitize_for_agentrouter(" not in sanit:
        block = None
        # Source 1: the skill's own asset — the canonical extracted block from
        # the live working tree (self-contained; includes the wire-target gate).
        asset_block = SKILL_DIR / "assets" / "message_sanitizer_block.txt"
        if asset_block.exists() and "def sanitize_for_agentrouter(" in asset_block.read_text(encoding="utf-8"):
            block = asset_block.read_text(encoding="utf-8")
            print("  sanitizer block <- skill asset")
        else:
            # Source 2: git snapshots (legacy fallback).
            for spec in GIT_SNAPSHOT_SOURCES:
                snap = git_show(spec, "agent/message_sanitization.py")
                if snap:
                    block = extract_sanitizer_block(snap)
                    if block:
                        print(f"  sanitizer block <- {spec}")
                        break
        assert block, "no source carried the sanitizer block"
        sanit = sanit.rstrip() + "\n\n\n" + block
        m = re.search(r"__all__\s*=\s*\[(.*?)\]", sanit, re.DOTALL)
        if m and '"sanitize_for_agentrouter"' not in m.group(1):
            sanit = sanit[:m.start(1)] + (
                m.group(1).rstrip()
                + '\n    "sanitize_for_agentrouter",\n    "_defang_sensitive_words",\n'
            ) + sanit[m.end(1):]
        SANIT.write_text(sanit, encoding="utf-8")
        changed.append("message_sanitization.py")

    # 2) helpers: import + dumper + three sites + guard
    helpers = HELPERS.read_text(encoding="utf-8")
    if "sanitize_for_agentrouter,\n)" not in helpers:
        ok = replace_first(
            "from agent.message_sanitization import (\n"
            "    _sanitize_surrogates,\n"
            "    _repair_tool_call_arguments,\n"
            ")",
            "from agent.message_sanitization import (\n"
            "    _sanitize_surrogates,\n"
            "    _repair_tool_call_arguments,\n"
            "    sanitize_for_agentrouter,\n"
            ")",
        )
        if ok:
            changed.append("helpers:import")
    if "def _maybe_dump_agentrouter_payload(" not in helpers:
        dumper = '''
# --- agentrouter.org debug payload dumper -----------------------------------
_AR_DUMP_FLAG = "/tmp/ar_dump_on"
_AR_DUMP_PATH = "/tmp/ar_payloads.jsonl"


def _maybe_dump_agentrouter_payload(tag: str, api_kwargs: dict, provider: str) -> None:
    """Append an outbound agentrouter payload to /tmp/ar_payloads.jsonl if the dump flag is set."""
    try:
        if not os.path.exists(_AR_DUMP_FLAG):
            return
        if not (provider or "").startswith("agentrouter"):
            return
        import json as _json
        with open(_AR_DUMP_PATH, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps({"tag": tag, "provider": provider, "kwargs": api_kwargs},
                                 ensure_ascii=False, default=str) + "\\n")
    except Exception:
        pass
'''
        idx = helpers.find(DUMPER_ANCHOR)
        assert idx != -1, "dumper anchor not found"
        ins = idx + len(DUMPER_ANCHOR)
        helpers = helpers[:ins] + "\n" + dumper + helpers[ins:]
        changed.append("helpers:dumper")
    if not re.search(r"def _dispatch_nonstreaming_api_request.*?sanitize_for_agentrouter\(api_kwargs", helpers, re.DOTALL):
        ok = replace_first(
            '    this helper only issues the request.\n    """\n',
            '    this helper only issues the request.\n    """\n'
            '    _maybe_dump_agentrouter_payload("dispatch", api_kwargs, getattr(agent, "provider", ""))\n'
            "    api_kwargs = sanitize_for_agentrouter(api_kwargs, getattr(agent, \"provider\", \"\"))\n",
        )
        if ok:
            changed.append("helpers:dispatch-site")
    if not re.search(r"def _open_stream.*?sanitize_for_agentrouter\(", helpers, re.DOTALL):
        ok = replace_first(
            "        def _open_stream(next_api_kwargs: dict[str, Any]):\n",
            "        def _open_stream(next_api_kwargs: dict[str, Any]):\n"
            '            _maybe_dump_agentrouter_payload("stream", next_api_kwargs, getattr(agent, "provider", ""))\n'
            "            next_api_kwargs = sanitize_for_agentrouter(\n"
            '                next_api_kwargs, getattr(agent, "provider", "")\n'
            "            )\n",
        )
        if ok:
            changed.append("helpers:stream-site")
    if not re.search(r"# Strip all remaining underscore-prefixed.*?sanitize_for_agentrouter\(\s*api_messages", helpers, re.DOTALL):
        anchor = ('                for internal_key in [k for k in api_msg if isinstance(k, str) and k.startswith("_")]:\n'
                  "                    api_msg.pop(internal_key, None)\n")
        idx = helpers.find(anchor)
        assert idx != -1, "summary sweep anchor not found"
        ins = idx + len(anchor)
        inject = (
            "\n"
            "        # agentrouter.org Filter A — defang sensitive words on the outbound\n"
            "        # summary request (hand-built; bypasses dispatch AND streaming).\n"
            "        _maybe_dump_agentrouter_payload(\n"
            '            "iteration_summary", {"model": agent.model, "messages": api_messages},\n'
            '            getattr(agent, "provider", ""),\n'
            "        )\n"
            "        api_messages = sanitize_for_agentrouter(\n"
            '            api_messages, getattr(agent, "provider", "")\n'
            "        )\n"
        )
        helpers = helpers[:ins] + inject + helpers[ins:]
        changed.append("helpers:summary-site")
    if not re.search(r"def _iter_provider_stream_chunks.*?if chunk is None:", helpers, re.DOTALL):
        injected = False
        # Shape A: pristine upstream iterator (`yield from stream`) — what a
        # fresh update / desktop --keep-stash leaves behind.
        shape_a = (
            "    try:\n        yield from stream\n    except json.JSONDecodeError as error:",
            "    try:\n"
            "        for chunk in stream:\n"
            "            if chunk is None:\n"
            "                continue  # agentrouter.org literal `data: null` SSE frame\n"
            "            yield chunk\n"
            "    except json.JSONDecodeError as error:",
        )
        # Shape B: partially-edited iterator — guard lines removed individually,
        # leaving `for chunk in stream:` + a bare `yield chunk`.
        shape_b = (
            "        for chunk in stream:\n            yield chunk",
            "        for chunk in stream:\n"
            "            if chunk is None:\n"
            "                continue  # agentrouter.org literal `data: null` SSE frame\n"
            "            yield chunk",
        )
        for old, new in (shape_a, shape_b):
            if old in helpers:
                helpers = helpers.replace(old, new, 1)
                injected = True
                break
        if injected:
            changed.append("helpers:null-guard")
        else:
            print("WARN: null-chunk guard NOT restored — iterator shapes A/B not found; needs manual merge")
    restore_regression_tests(changed)

    if changed and any(c.startswith("helpers:") for c in changed):
        HELPERS.write_text(helpers, encoding="utf-8")

    if changed:
        print("APPLIED:", ", ".join(changed))
        print("NOW RUN: scripts/run_tests.sh tests/agent/test_agentrouter_filter_defang.py "
              "tests/run_agent/test_agentrouter_null_stream_chunk.py")
        return 1
    print("all layers already present — nothing to do")
    return 0


def check() -> int:
    missing = []
    for name, probe in LAYERS:
        try:
            ok = bool(probe())
        except Exception:
            ok = False
        print(f"  {'✓' if ok else '✗ MISSING'}  {name}")
        if not ok:
            missing.append(name)
    if missing:
        print(f"\n{len(missing)} layer(s) missing — an update probably wiped them.")
        print("Run: python3 " + __file__ + " --apply")
        return 1
    print("\nall agentrouter layers present")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()
    sys.exit(check() if args.check else apply())
