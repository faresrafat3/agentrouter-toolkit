# agentrouter.org auth & key-quota quirks (verified 2026-08-10)

## MANDATORY User-Agent header
Every request to agentrouter.org MUST carry:
```
User-Agent: claude-cli/1.0.0 (external, cli)
```
Without it, EVERY key (valid or not) returns:
```json
{"error":{"message":"unauthorized client detected, contact support for assistance at https://discord.gg/aYq5B4RW3"},"message":"UNAUTHENTICATED","success":false,"type":"unauthorized_client_error"}
```
This is NOT a key problem — it is a missing-header problem. If `curl /v1/models`
returns `UNAUTHENTICATED`, add the header BEFORE assuming the key is dead.
Hermes sets this via `default_headers` / `extra_headers: User-Agent: ...` in each
`agentrouter-org-N` provider block in `config.yaml`.

## How to tell a WORKING key from a QUOTA-EXHAUSTED key
`GET /v1/models` is NOT a valid quota probe: it returns HTTP 200 even for keys
with zero quota (as long as the User-Agent header is present). It only proves
the key+header are accepted, not that you can actually run a model.
Probe with a real completion instead:
```
POST /v1/chat/completions
{"model":"claude-opus-5","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":10}
```
- HTTP 200 + content  -> key has quota, working
- HTTP 403 "user quota is not enough" -> key EXHAUSTED (drop it from config)
- HTTP 401/500        -> key invalid or header missing

## Minimal-token verification (don't burn quota)
Use `max_tokens: 3-10` on every probe. One `max_tokens:10` opus-5 call is enough
to prove the default profile routes correctly. Fares prefers low-token verification.

## curl template
```bash
UA="User-Agent: claude-cli/1.0.0 (external, cli)"
curl -s https://agentrouter.org/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "$UA" -H "Content-Type: application/json" \
  --max-time 90 \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":"OK"}],"max_tokens":10}'
```
