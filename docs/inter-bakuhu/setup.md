# Inter-Bakuhu Network

Connect multiple Bakuhu instances across machines — delegate tasks from your primary shogun to secondary shogun instances over a secure Tailscale VPN.

## Background

Inter-Bakuhu Network is a network feature provided by this project (shogun-web / Tenshukaku). `BakuhuNode` serves the `/bakuhu/*` endpoints, enabling task delegation between multiple shogun-web instances. It is activated when a `bakuhu` config block is present in `config/settings.yaml`. Designed for integration with [multi-agent-bakuhu](https://github.com/yohey-w/multi-agent-shogun) — an independent multi-agent system.

If you do not use the Inter-Bakuhu feature, this document does not apply.

## Overview

The Inter-Bakuhu Network enables a **primary shogun** (your main machine) to delegate tasks to one or more **secondary shogun** instances running on remote machines. Communication uses WebSocket RPC/PubSub via [fastapi-websocket-rpc](https://github.com/permitio/fastapi-websocket-rpc) and [fastapi-websocket-pubsub](https://github.com/permitio/fastapi-websocket-pubsub), hosted inside the Tenshukaku server process.

Key properties:

- **Primary only accepts user input** — secondary instances are execution-only
- **Connection ownership is fixed** — primary always initiates; secondary only listens
- **Automatic reconnection** — exponential backoff (2s → 60s) keeps the network resilient
- **Token authentication** — each peer has its own token; no shared secrets

## Architecture

```
User
  ↓
Primary Tenshukaku (sole user-input endpoint)
  ↓ WebSocket RPC: submit_delegation (1:N)
  ├→ Secondary Tenshukaku A
  ├→ Secondary Tenshukaku B
  └→ Secondary Tenshukaku N
         ↓ existing mailbox (inbox_write.sh)
       Karo · Ashigaru
         ↑ WebSocket RPC callback: push_result
       Primary Tenshukaku
```

`Tenshukaku` refers to this project (shogun-web). `BakuhuNode` runs inside it as a native feature of this project and provides the `/bakuhu/*` endpoints.

### Connection establishment

```
Primary BakuhuNode
  → maintain_rpc_client()    WS /bakuhu/ws/rpc?token=<outbound_token>
  → maintain_pubsub_client() WS /bakuhu/ws/pubsub?token=<outbound_token>
```

Only the **primary shogun** establishes outbound connections. Secondary instances never initiate connections back to primary — callbacks (`push_result`, `push_status`) travel over the same RPC channel that primary opened.

### Delegation flow

1. Primary calls `submit_delegation(request_id, content, from_bakuhu, priority)` via RPC
2. Secondary persists the request to `queue/inbox/shogun.yaml` (idempotent, flock-guarded)
3. Secondary agents process the task through the normal mailbox system
4. Secondary calls `push_result(request_id, summary, status, artifact_path)` as RPC callback
5. Primary receives the result and persists it to its own inbox

### State transitions

```
received → validated → queued → in_progress → succeeded
                                             → failed
                                             → expired
                                             → canceled
```

Intermediate state changes are reported via `push_status` callbacks and `bakuhu.events` PubSub topic.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Tailscale VPN** | All inter-Bakuhu communication must stay within the Tailscale network. Do not expose port 30001 to the public internet. |
| **shogun-web (Tenshukaku)** | This project must be running on each machine. The `BakuhuNode` extension activates at startup when `bakuhu` config is present. |
| **Python dependencies** | `fastapi-websocket-rpc` and `fastapi-websocket-pubsub` must be installed (included in `pyproject.toml`). |
| **multi-agent-bakuhu** | A fully configured Bakuhu instance must be running on every machine in the network. |

## Configuration

All settings live in `config/settings.yaml` under the `bakuhu` key. Copy `config/settings.yaml.example` as a starting point.

### Primary Shogun settings

```yaml
bakuhu:
  base_path: "/path/to/your/multi-agent-bakuhu"
  role: primary
  name: "primary-bakuhu"
  outbound_token: "your-outbound-token-here"
  accepted_tokens:
    your-secondary-token-here: "secondary-a"
  upload_dir: "queue/cross_bakuhu/files"
  peers:
    - id: "secondary-a"
      name: "Secondary Bakuhu A"
      base_url: "http://your-secondary-tailscale-ip:30001"
    - id: "secondary-b"
      name: "Secondary Bakuhu B"
      base_url: "http://your-secondary-tailscale-ip-b:30001"
```

### Secondary Shogun settings

```yaml
bakuhu:
  base_path: "/path/to/your/multi-agent-bakuhu"
  role: secondary
  name: "secondary-bakuhu-a"
  outbound_token: "your-secondary-token-here"
  accepted_tokens:
    your-primary-token-here: "primary-bakuhu"
  upload_dir: "queue/cross_bakuhu/files"
  # peers: not needed on secondary (secondary never initiates connections)
```

### Environment variable overrides

`accepted_tokens` values can be overridden without editing `settings.yaml`:

```bash
# Token key → uppercase + replace non-alphanumeric with _
# "token-secondary-a" → BAKUHU_ACCEPTED_TOKENS_TOKEN_SECONDARY_A
export BAKUHU_ACCEPTED_TOKENS_TOKEN_SECONDARY_A=secondary-a
```

If two token strings map to the same environment variable key (key collision), the server refuses to start.

## How It Works

### 1. Initial connection (POST /bakuhu/connect)

```
Primary                         Secondary
   │                               │
   │── GET /bakuhu/healthz ────────►│  (reachability check only)
   │◄─────────────────── 200 OK ───│
   │── WS /bakuhu/ws/rpc?token=T ──►│  RPC channel (primary sends client methods)
   │◄─────── RPC channel ready ────│
   │── WS /bakuhu/ws/pubsub?token=T►│  PubSub subscription
   │◄──────── PubSub ready ────────│
```

### 2. Task delegation

```
Primary                         Secondary
   │                               │
   │── submit_delegation() ────────►│
   │◄── {accepted: true, ...} ─────│
   │                               │── inbox_write → Karo/Ashigaru
   │                               │── (work happens here)
   │◄── push_status("in_progress") │
   │◄── push_result("succeeded")───│
   │◄── PubSub event ──────────────│
```

### 3. Automatic reconnection

When a connection drops, `maintain_rpc_client()` and `maintain_pubsub_client()` automatically reconnect with exponential backoff:

| Error type | Initial delay | Maximum delay |
|------------|--------------|---------------|
| Network failure | 2 seconds | 60 seconds |
| Auth/config error (401/403) | 10 seconds | 300 seconds |

PubSub **re-subscribes** on every reconnection to avoid missing events.

## Security Considerations

### Token management

- **Use unique tokens per peer** — never reuse `outbound_token` across multiple instances
- `changeme` is for **development only**; replace before connecting to any non-local machine
- Token rotation procedure: issue new token → update all peer configs → invalidate old token

### Network

- **Tailscale VPN is required** — inter-Bakuhu traffic is designed for a closed VPN network
- Do **not** expose port 30001 to the public internet
- Tenshukaku runs on port 30001 by default; restrict firewall rules to Tailscale interface only

### Firewall

```bash
# Example: allow port 30001 only from Tailscale network (100.x.x.x range)
sudo ufw allow from 100.64.0.0/10 to any port 30001
sudo ufw deny 30001
```

### Secrets

- `config/settings.yaml` is listed in `.gitignore` — **never commit it**
- `config/settings.yaml.example` must contain only placeholder values (no real IPs, no real tokens)
- Tokens must not appear in logs — the server masks `?token=` in access logs as `?token=***`

### Role enforcement

- primary initiates `submit_delegation` calls to secondary
- `push_result` / `push_status` callbacks travel from secondary back to primary over the same RPC channel
- Secondary attempting to call `POST /bakuhu/connect` on primary is rejected (403)

### Token rotation

Rotate tokens periodically, especially after:
- A team member leaves
- A machine is decommissioned
- Any suspected credential exposure

Procedure: generate new tokens on all peers → update `accepted_tokens` on each server → restart → verify connectivity → remove old tokens.

## Troubleshooting

### Secondary shows `offline` in /bakuhu/peers

1. Verify shogun-web is running on the secondary machine: `curl http://<secondary-ip>:30001/bakuhu/healthz`
2. Verify Tailscale is connected on both machines: `tailscale status`
3. Check secondary's `accepted_tokens` — the primary's `outbound_token` must be listed
4. Check primary's `peers[].base_url` — must use the Tailscale IP (100.x.x.x), not a LAN IP
5. Review shogun-web logs for auth errors: look for `token rejected` or `401`

### submit_delegation returns `{"accepted": false, "reason": "duplicate"}`

This is expected behavior — the same `request_id` was already received. The system is idempotent by design. Generate a new `request_id` for each new delegation.

### push_result not arriving at primary

1. Check `queue/cross_bakuhu/pending_results.yaml` on secondary — results queue up here when the callback connection is unavailable
2. The pending queue drains automatically once the RPC channel reconnects
3. If the queue grows unboundedly, check for auth errors (secondary's `outbound_token` must match an entry in primary's `accepted_tokens`)

### Token collision on startup

```
ERROR: accepted_tokens key collision: 'token-a.b' and 'token_a-b' both map to TOKEN_A_B
```

Two token strings in `accepted_tokens` produce the same environment variable key after normalization. Rename one of the tokens to eliminate the collision.

### Connection immediately drops (auth/config backoff)

When the connection drops and reconnects very slowly (10s → 20s → ... → 300s), the server has detected an auth or config error. Check:
- `outbound_token` on the connecting side matches an `accepted_tokens` entry on the receiving side
- The receiving server is actually running bakuhu mode (not a plain shogun-web instance without bakuhu config)
