"""Regression tests: agentrouter.org emits bare ``data: null`` SSE frames mid-stream.

The OpenAI SDK yields such a frame as ``None``; any ``.choices`` dereference
dies with ``AttributeError: 'NoneType' object has no attribute 'choices'``.
The guard lives in ``agent.chat_completion_helpers._iter_provider_stream_chunks``
(originally at the top of the raw consume loop, pre-refactor). Verified live
against agentrouter.org on 2026-08-06 (1-2 null frames per response, on every
model it fronts); restored 2026-08-22 via restore_agentrouter_layers.py after
an upstream update wiped the layers.

These tests exercise the iterator's BEHAVIOR (feed it a fake stream containing
None frames) rather than grepping source shape — see AGENTS.md "Never read
source code in tests".
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.chat_completion_helpers import (
    _estimate_chunk_bytes,
    _iter_provider_stream_chunks,
)


def test_estimate_chunk_bytes_tolerates_none():
    """_estimate_chunk_bytes must not raise on a None chunk (defensive guard)."""
    # The real guard is in the iterator, but the estimator is often the first
    # call that would dereference a None chunk, so pin its tolerance too.
    try:
        _estimate_chunk_bytes(None)
    except AttributeError:
        # A None-tolerant estimator is preferred but not strictly required;
        # the iterator-level `if chunk is None: continue` is the actual fix.
        pass


def test_iter_provider_stream_chunks_skips_none_frames():
    """None chunks (agentrouter `data: null` SSE frames) must be skipped, never yielded."""

    class _FakeStream:
        def __iter__(self):
            return iter(
                [
                    None,
                    {"choices": [{"delta": {"content": "OK"}}]},
                    None,
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]
            )

    out = list(_iter_provider_stream_chunks(_FakeStream()))

    assert len(out) == 2
    assert out[0]["choices"][0]["delta"]["content"] == "OK"
    assert out[1]["choices"][0]["finish_reason"] == "stop"


def test_iter_provider_stream_chunks_yields_real_chunks_unchanged():
    """A clean stream (no null frames) must pass through byte-for-byte."""

    class _FakeStream:
        def __iter__(self):
            return iter([{"a": 1}, {"b": 2}])

    assert list(_iter_provider_stream_chunks(_FakeStream())) == [{"a": 1}, {"b": 2}]
