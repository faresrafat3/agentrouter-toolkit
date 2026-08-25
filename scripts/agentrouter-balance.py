#!/usr/bin/env python3
"""Live AgentRouter key-balance board.

Reads AGENTROUTER_KEY_* from ~/.hermes/.env (names only are ever printed),
then probes each key against agentrouter.org:

  Probe A (auth)      GET /v1/models            -> key valid + UA accepted
  Probe B (pre-consume) POST /v1/chat/completions with max_tokens=60000
        -> the server reserves ~$0.24-0.62 up front; an account with almost
           no balance FAILS here even though tiny requests still pass.

Why not a tiny completion? Verified 2026-08-23: an account down to $0.0165
still serves max_tokens=8 (need < residual), so a tiny probe LIES about
balance. Only the large pre-consume gate separates funded vs exhausted.

Usage:  python3 agentrouter-balance.py [--max-tokens N]
Exit codes: 0 = at least one funded key, 1 = none funded/reachable.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://agentrouter.org"
UA = "claude-cli/1.0.0 (external, cli)"


def load_env_keys(env_path="~/.hermes/.env"):
    """Parse .env text for AGENTROUTER_KEY_<n> (no import side effects)."""
    path = os.path.expanduser(env_path)
    keys = {}
    if not os.path.exists(path):
        return keys
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"\s*AGENTROUTER_KEY_(\d+)\s*=\s*(\S+)\s*$", line)
        if m:
            keys[f"KEY_{m.group(1)}"] = m.group(2).strip()
    return dict(sorted(keys.items()))


def mask(tok):
    return f"{tok[:7]}...{tok[-4:]}" if len(tok) > 14 else "<short>"


def http(url, key, body=None, timeout=45):
    headers = {"User-Agent": UA, "Authorization": f"Bearer {key}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # network window / DNS / TLS
        return None, f"{type(e).__name__}: {e}"


def classify_quota(text):
    m = re.search(
        r"user quota:\s*[＄$]?([0-9.]+).*?need quota:\s*[＄$]?([0-9.]+)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def probe_key(label, key, max_tokens):
    status, text = http(f"{BASE}/v1/models", key, timeout=20)
    auth = "auth-OK" if status == 200 else f"auth-{status or 'FAIL'}"

    body = {"model": "claude-opus-5", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": "hi"}]}
    status, text = http(f"{BASE}/v1/chat/completions", key, body=body)
    if status == 200:
        verdict = "FUNDED"
    elif status == 403 and "quota" in text.lower():
        resid, _need = classify_quota(text)
        verdict = f"EXHAUSTED (residual ${resid:.4f})" if resid else "EXHAUSTED"
    elif status == 401:
        verdict = "BAD/UNAUTHORIZED"
    elif status is None and "Timeout" in text:
        # A FUNDED account accepts the reservation and actually generates,
        # which can outlast the read timeout. Re-probe with a smaller
        # reservation: exhausted accounts still fail fast with 403 here
        # (need quota exceeds their residual), funded ones return quickly.
        status, text = http(f"{BASE}/v1/chat/completions", key,
                            body={**body, "max_tokens": min(8000, max_tokens)},
                            timeout=30)
        if status == 200:
            verdict = "FUNDED"
        elif status == 403 and "quota" in text.lower():
            resid, _need = classify_quota(text)
            verdict = f"EXHAUSTED (residual ${resid:.4f})" if resid else "EXHAUSTED"
        else:
            verdict = f"SLOW/UNSURE ({text.splitlines()[0][:40]})"
    elif status is None:
        verdict = f"NETWORK ({text.splitlines()[0][:40]})"
    else:
        verdict = f"HTTP {status}: {text[:60]}"
    print(f"{label}  {mask(key)}  {auth:9s}  {verdict}")
    return status == 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tokens", type=int, default=60000,
                    help="pre-consume size (bigger => stricter balance gate)")
    ap.add_argument("--env", default="~/.hermes/.env")
    args = ap.parse_args()

    keys = load_env_keys(args.env)
    env_extra = {k: v for k, v in os.environ.items()
                 if re.match(r"AGENTROUTER_KEY_\d+$", k)}
    for k, v in env_extra.items():
        keys.setdefault(k.replace("AGENTROUTER_", ""), v)

    if not keys:
        print("No AGENTROUTER_KEY_* found in", args.env)
        return 1

    print(f"AgentRouter balance board (pre-consume {args.max_tokens:,} tokens)\n")
    any_funded = False
    for label, key in keys.items():
        if probe_key(label, key, args.max_tokens):
            any_funded = True
    return 0 if any_funded else 1


if __name__ == "__main__":
    sys.exit(main())
