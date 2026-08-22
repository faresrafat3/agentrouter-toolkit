# agentrouter.org key verification recipe

Use this to triage a batch of keys (which are funded vs exhausted vs bad) and to
diagnose a `401 unauthorized client` before concluding a key is dead.

## The mandatory User-Agent header

agentrouter.org rejects any request that lacks
`User-Agent: claude-cli/1.0.0 (external, cli)` with:

```
HTTP 401 {"error":{"message":"unauthorized client detected, contact support
for assistance at https://discord.gg/aYq5B4RW3"},"message":"UNAUTHORIZED",
"success":false,"type":"unauthorized_client_error"}
```

This fires EVEN FOR A VALID, FUNDED KEY. It is independent of key validity.
Always send the header. In config.yaml set it in both places:

```yaml
model:
  default_headers:
    User-Agent: claude-cli/1.0.0 (external, cli)
providers:
  agentrouter-org-1:
    extra_headers:
      User-Agent: claude-cli/1.0.0 (external, cli)
```

## Probe 1 — does the key authenticate? (needs the header)

```bash
UA="User-Agent: claude-cli/1.0.0 (external, cli)"
curl -s https://agentrouter.org/v1/models \
  -H "Authorization: Bearer $KEY" -H "$UA" --max-time 20
```

- With header + valid key → `HTTP 200` with a `data` model list.
- Without header → `HTTP 401 unauthorized_client_error` (NOT a bad key — add the header).

## Probe 2 — is the key FUNDED? (`/models` lies)

`/v1/models` returns 200 for any valid-shaped key, even an exhausted one.
To actually confirm a key works, send a tiny chat completion:

```bash
UA="User-Agent: claude-cli/1.0.0 (external, cli)"
curl -s -o resp.json -w "HTTP %{http_code}\n" https://agentrouter.org/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "$UA" -H "Content-Type: application/json" \
  --max-time 90 \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":10}'
python3 -c "import json;d=json.load(open('resp.json'));print(d['choices'][0]['message']['content'] if 'choices' in d else d.get('error',{}).get('message','?'))"
```

Outcomes:
- `HTTP 200` + `OK` → funded, working. ✅
- `HTTP 403` + `user quota is not enough` → key valid but EXHAUSTED. ❌ Drop it.
- `HTTP 401 unauthorized_client_error` → missing User-Agent header (see above).
- `HTTP 503` + `当前分组 default 下对于模型 无可用渠道` → key fine, but the
  model/endpoint grouping has no channel for that model. Usually a provider/model
  misconfig, not a key problem. (Seen when AIAgent is instantiated without reading
  model.default from config.yaml in a test harness — pass provider/model/base_url
  explicitly to confirm the key itself works.)

## Triaging a batch (the pattern used 2026-08-10)

Given keys K1 K2 K3, loop both probes over each. Result found in practice:
one key exhausted (`403 user quota is not enough`), two funded (`200 OK`).
Replace the exhausted key's slot in `.env` with a funded key; keep all three
provider entries (`agentrouter-org-1/2/3`) pointing only at funded keys so MOA
and parallel delegation never hit the dead one.

## Note on editing config.yaml

`patch`/direct file writes to `~/.hermes/config.yaml` are REFUSED by the agent
(defense-in-depth: "cannot modify security-sensitive configuration"). Use
`hermes config set <dot.path> <value>` instead (e.g.
`hermes config set model.provider agentrouter-org-1`). `.env` CAN be edited via
the terminal tool directly.
