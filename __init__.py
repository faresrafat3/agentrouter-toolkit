"""agentrouter-toolkit — Hermes plugin package.

The local plugin loader imports this ``__init__.py``; the visible surface
(``hermes agentrouter status``) lives in :mod:`plugin_api` and is
re-exported here. Read-only visibility only — never mutates core files.
"""

from .plugin_api import register, status_text  # noqa: F401

__all__ = ["register", "status_text"]
