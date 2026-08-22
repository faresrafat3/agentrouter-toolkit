"""Regression tests: agentrouter.org content-filter defang (Filters A & C).

agentrouter.org fronts several models (claude-opus-5, gpt-5.6-sol, ...) and
applies deterministic content filters that the upstream provider does NOT:

  A. HTTP 500 `sensitive words detected`  — a SUBSTRING blocklist. Tripped by
     whole trigger words (VIOLATION, attack, ...) AND by the exact phrase
     "You are a helpful assistant." (the trailing period is the trigger).
  C. `data: null` SSE frame mid-stream       — handled in
     chat_completion_helpers.py (the `if chunk is None: continue` guard).

These tests pin the outbound sanitizer in agent/message_sanitization.py so a
future refactor cannot silently drop the defang. All assertions are LOCAL
(no network) except where explicitly noted.

Verified live 2026-08-06: the real 107KB Hermes system prompt goes 500→200.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.message_sanitization import (
    _defang_sensitive_words,
    sanitize_for_agentrouter,
)


def test_single_word_synonym_rewrite():
    out = _defang_sensitive_words("There is a VIOLATION and an attack here")
    assert "VIOLATION" not in out
    assert "breach" in out.lower()
    assert "probe\u200b-attempt" in out or "probe-attempt" in out.lower()


def test_trailing_dot_phrase_rewrite():
    # The exact phrase "You are a helpful assistant." (with period) is a
    # substring trigger; without the period it passes. Original casing kept.
    out = _defang_sensitive_words("You are a helpful assistant.")
    assert out == "You are a helpful assistant"
    # Other variants are untouched (not triggers).
    assert _defang_sensitive_words("You are an AI assistant.") == "You are an AI assistant."
    # lowercase variant also handled (matched case-insensitively, period dropped).
    assert _defang_sensitive_words("you are a helpful assistant.") == "you are a helpful assistant"


def test_hyphen_defang_breaks_substring():
    # "role-play" trips the filter via its halves; defanging with U+200B
    # breaks the substring match while staying byte-reversible.
    out = _defang_sensitive_words("use role-play mode")
    assert "role\u200b-play" in out
    # Dates / UUIDs / versions / ids / CLI flags must stay byte-identical.
    assert _defang_sensitive_words("2026-08-06") == "2026-08-06"
    assert _defang_sensitive_words("call_abc-123") == "call_abc-123"
    assert _defang_sensitive_words("--verbose") == "--verbose"


def test_non_agentrouter_is_noop():
    kw = {"messages": [{"role": "user", "content": "VIOLATION attack kill"}]}
    out = sanitize_for_agentrouter(kw, "openai")
    assert out["messages"][0]["content"] == "VIOLATION attack kill"
    # agentrouter-org-* variants ARE sanitized.
    out2 = sanitize_for_agentrouter(dict(kw), "agentrouter-org-1")
    assert "VIOLATION" not in out2["messages"][0]["content"]


def test_wire_target_gate_matches_by_url_not_label():
    """Live incident 2026-08-22: a session restored from old state carried
    provider='custom' (legacy registration) while pointing at
    https://agentrouter.org/v1 — the label-only gate skipped sanitization and
    the raw request hit Filter B (HTTP 400 content-blocked). The gate must
    key off the WIRE TARGET too."""
    # label says 'custom' but destination is agentrouter.org -> sanitize.
    def fresh(content="hijack the mainframe"):
        # fresh deep structure per case: the sanitizer mutates messages
        # in place (documented), so a shallow dict() copy would leak state.
        return {"messages": [{"role": "user", "content": content}]}

    out = sanitize_for_agentrouter(
        fresh(), "custom", base_url="https://agentrouter.org/v1"
    )
    assert "hijack" not in out["messages"][0]["content"]
    # name-only path still works without a base_url (back-compat).
    out2 = sanitize_for_agentrouter(fresh(), "agentrouter-1")
    assert "hijack" not in out2["messages"][0]["content"]
    # genuinely different host -> untouched, even with a custom-ish label.
    out3 = sanitize_for_agentrouter(
        fresh(), "custom", base_url="https://api.stepfun.ai/v1"
    )
    assert out3["messages"][0]["content"] == "hijack the mainframe"


def test_sanitize_walks_system_and_messages():
    kw = {
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "VIOLATION here"}],
    }
    out = sanitize_for_agentrouter(kw, "agentrouter-org-2")
    assert out["system"] == "You are a helpful assistant"
    assert "VIOLATION" not in out["messages"][0]["content"]


def test_structural_fields_untouched():
    # tool_calls / name / role must NOT be walked or mutated.
    kw = {
        "messages": [
            {
                "role": "assistant",
                "content": "VIOLATION",
                "tool_calls": [
                    {"id": "call_abc-123", "function": {"name": "attack", "arguments": "{}"}}
                ],
            }
        ]
    }
    out = sanitize_for_agentrouter(kw, "agentrouter-org-3")
    tc = out["messages"][0]["tool_calls"][0]
    # content is defanged...
    assert "VIOLATION" not in out["messages"][0]["content"]
    # ...but structural fields keep their original bytes.
    assert tc["id"] == "call_abc-123"
    assert tc["function"]["name"] == "attack"
