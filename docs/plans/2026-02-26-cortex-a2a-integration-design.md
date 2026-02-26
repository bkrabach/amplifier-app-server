# Cortex A2A Integration Design

## Goal

Integrate Cortex into a 5-agent A2A (Agent-to-Agent) mesh using the Google A2A protocol via the `amplifier-bundle-a2a` bundle, enabling peer agents to query Cortex for notification intelligence and enabling Cortex to proactively notify ai-os of high-urgency events.

## Background

Cortex is the attention management platform in a multi-agent ecosystem alongside ai-os, lifeline, lifeline-demo, and hive-slack. Currently these agents operate independently. The A2A protocol enables them to communicate as peers — querying each other's capabilities and proactively sharing information.

Cortex's unique value in the mesh is its deep notification intelligence: scored notification history, attention state, focus mode status, and content search across all notification sources. Other agents need this context to make informed decisions (e.g., ai-os assembling a morning briefing needs to know what notifications came in overnight).

### Reference Documents

- A2A Handoff Pack: `/home/bkrabach/dev/all-a2a/docs/handoffs/cortex-a2a-handoff.md`
- A2A Bundle: `git+https://github.com/microsoft/amplifier-bundle-a2a@main`

## Approach

**Option C — Dedicated A2A Session + Tool in Web Chat.** Two integration points:

1. **A dedicated `cortex-a2a` session** — runs permanently in the server, handles all incoming A2A messages autonomously, and broadcasts proactive alerts. Has the A2A server hook (port 8214), A2A tool, and notification/policies tools.

2. **`tool-a2a` added to `cortex-core.md`** — gives the user the ability to manually send A2A messages from the web chat (e.g., "ask lifeline who Dan Shapiro is"). No server hook here (would conflict on port).

This separates concerns cleanly: the autonomous responder runs independently of user chat sessions, while the user retains the ability to manually reach peers.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                amplifier-app-server              │
│                                                  │
│  ┌──────────────┐       ┌──────────────────────┐ │
│  │  cortex-core  │       │    cortex-a2a         │ │
│  │  (web chat)   │       │  (autonomous session) │ │
│  │               │       │                       │ │
│  │  + tool-a2a   │       │  + hooks-a2a-server   │ │
│  │  (outbound    │       │    (port 8214)        │ │
│  │   only)       │       │  + tool-a2a           │ │
│  │               │       │  + notification tools │ │
│  │  + a2a-network│       │  + policies tools     │ │
│  │    .md context│       │  + a2a-network.md     │ │
│  └──────────────┘       └──────────┬───────────┘ │
│                                     │             │
│  ┌──────────────────┐               │             │
│  │ notification_    │  score >= 0.9 │             │
│  │ processor.py     │──────────────►│             │
│  └──────────────────┘               │             │
└─────────────────────────────────────┼─────────────┘
                                      │ A2A protocol
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
              ┌─────▼─────┐   ┌──────▼──────┐   ┌──────▼──────┐
              │   ai-os    │   │  lifeline   │   │ hive-slack  │
              │  :8210     │   │  :8211/:8212│   │  :8213      │
              └────────────┘   └─────────────┘   └─────────────┘
```

## Components

### New File: `bundles/cortex-a2a.md`

The dedicated A2A session bundle:

```yaml
includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - behavior: git+https://github.com/microsoft/amplifier-bundle-a2a@main#subdirectory=behaviors/a2a.yaml

session:
  orchestrator:
    module: loop-streaming
  context:
    module: context-simple

providers:
  - module: provider-anthropic
    source: git+https://github.com/microsoft/amplifier-module-provider-anthropic@main
    config:
      model: claude-sonnet-4-5

hooks:
  - module: hooks-a2a-server
    source: git+https://github.com/microsoft/amplifier-bundle-a2a@main#subdirectory=modules/hooks-a2a-server
    config:
      port: 8214
      agent_name: "cortex"
      agent_description: "Attention management platform with deep notification intelligence. Scores notifications for relevance, manages focus modes, and maintains a rich queryable history of all notification content and context that has flowed across the user's devices."
      agent_skills:
        - attention-state
        - notification-score
        - focus-mode-status
        - notification-history
        - notification-content-search
      realtime_response: false
      discovery:
        mdns: false
      known_agents:
        - name: ai-os
          url: http://localhost:8210
          tier: trusted
        - name: lifeline
          url: http://localhost:8211
          tier: trusted
        - name: lifeline-demo
          url: http://localhost:8212
          tier: trusted
        - name: hive-slack
          url: http://localhost:8213
          tier: trusted

tools:
  - module: tool-a2a
    source: git+https://github.com/microsoft/amplifier-bundle-a2a@main#subdirectory=modules/tool-a2a
  - module: tool-filesystem
    config:
      allowed_write_paths:
        - "{server_root}/config"
```

The notification and policies tools are mounted programmatically in `session_manager.py` (same pattern as cortex-core sessions).

**System prompt directives:**
- You are Cortex's autonomous A2A responder
- Answer incoming messages from peer agents using your notification tools
- You don't interact with a human user — respond autonomously
- For notification history queries, use the notifications tool
- For attention state queries, summarize current notification stats and focus mode
- You have filesystem access to update config/attention-rules.md

**Skills advertised to the network:**

| Skill | Description |
|-------|-------------|
| `attention-state` | Current notification stats, suppression rates, active focus mode |
| `notification-score` | Score a hypothetical notification against current rules |
| `focus-mode-status` | Whether user is in focus mode, what rules are active |
| `notification-history` | Query recent notifications by app, sender, time, urgency |
| `notification-content-search` | Search notification content for specific topics, people, keywords |

### Modified: `bundles/cortex-core.md`

Add only:
- `tool-a2a` with source (no server hook — avoids port conflict)
- `context/a2a-network.md` as a context include

This lets users send A2A messages from the web chat (e.g., "ask lifeline who Dan Shapiro is").

### New File: `context/a2a-network.md`

Shared context file used by both bundles. Three sections:

**Top — Network Directory:**
All 5 agents with URLs, descriptions, and skills. Identifies "cortex" as "THIS IS YOU."

**Middle — Your Role:**
- Handle attention state, notification scoring, focus mode, notification history locally
- Route to ai-os for calendar context to assess urgency
- Route to lifeline for sender relationship context
- Route to hive-slack for Slack channel context or coding tasks
- Don't reach out when you can answer locally

**Bottom — Proactive Triggers (CUSTOMIZABLE):**
- Notification scored >= 0.9 → notify ai-os only (default)
- Focus mode change → notify ai-os only (default)
- Notification burst from single source → notify ai-os only (default)
- Explicit note that these are defaults and the user can customize them
- The LLM can edit this file to update rules when instructed

## Data Flow

### Incoming A2A Query (e.g., ai-os asks "what notifications came in overnight?")

```
Peer agent sends A2A message
    → hooks-a2a-server receives on port 8214
    → Injects as prompt into cortex-a2a session
    → LLM uses notification tools to query history
    → LLM formulates response
    → hooks-a2a-server returns response to peer
```

### Proactive Broadcast (high-urgency notification arrives)

```
Notification arrives → Processor scores it → Score >= 0.9
    → Processor calls session_manager.execute("cortex-a2a", prompt=<formatted alert>)
    → LLM reads proactive trigger rules from a2a-network.md context
    → LLM uses tool-a2a to send to ai-os only
```

### User-Initiated A2A (from web chat)

```
User types "ask lifeline who Dan Shapiro is" in web chat
    → cortex-core session processes the message
    → LLM uses tool-a2a to send query to lifeline
    → Response returned in chat
```

### Focus Mode Change

```
User toggles focus mode via web UI or command
    → Server injects prompt into cortex-a2a session:
      "User just entered Focus Mode. Per routing rules, notify ai-os."
    → LLM uses tool-a2a to notify ai-os
```

## Server Integration

### `server.py` (lifespan startup)

After existing initialization (stores, LLM scorer, etc.):

1. Create the cortex-a2a session: `session_manager.create_session(bundle="bundles/cortex-a2a.md", session_id="cortex-a2a")`
2. This triggers the A2A behavior to mount, starting the HTTP server on port 8214
3. Log confirmation that A2A is ready

### `notification_processor.py`

After scoring a notification >= 0.9:

1. Check if cortex-a2a session exists
2. Call `session_manager.execute(session_id="cortex-a2a", prompt=<formatted alert>)`
3. Wrap in try/except — A2A broadcasting failure must not block notification processing
4. Log the broadcast attempt and result

### `session_manager.py`

- The cortex-a2a session gets notification/policies tools mounted programmatically, same as cortex-core sessions
- May need a small update to the tool mounting logic to recognize the cortex-a2a session ID

## Error Handling

| Failure | Behavior |
|---------|----------|
| A2A session creation fails on startup | Log error, continue running. Server works without A2A. |
| A2A broadcast fails during notification processing | Log warning, don't block notification pipeline. |
| Port 8214 already in use | Log error. A2A features unavailable but server continues. |
| Peer agent unreachable | tool-a2a handles timeouts internally; LLM gets error response. |

## Testing Strategy

Per the handoff doc's testing checklist:

1. **Server startup** — Start server, confirm A2A server starts on port 8214 in logs
2. **Agent card** — `curl http://localhost:8214/.well-known/agent.json` → verify agent card with name "cortex" and all 5 skills
3. **Outbound from web chat** — From web chat, use tool-a2a to send a message to a peer
4. **Inbound autonomous response** — Have a peer agent send a message, confirm autonomous response
5. **Proactive broadcast** — Trigger a high-urgency notification, confirm broadcast to ai-os via A2A
6. **Focus mode notification** — Toggle focus mode, confirm ai-os notification

## Open Questions

- The A2A bundle's hooks-a2a-server hook skips child sessions via parent_id check. Need to verify the cortex-a2a session created by session_manager has no parent_id (it shouldn't, since it's a root session).
- The notification/policies tools are mounted programmatically in session_manager.py. Need to extend that logic to also mount them for the cortex-a2a session (currently only does it for cortex-core sessions).
- Port 8214 needs to be accessible from wherever the other agents are running. If they're all on the same machine (localhost), this works. If distributed, may need Tailscale or similar.
