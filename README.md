# Amplifier App Server

Always-on AI agent runtime with HTTP/WebSocket API. Hosts persistent Amplifier sessions that can be accessed from multiple clients and extended via bundles.

## Features

- **Multi-session hosting** - Run multiple Amplifier sessions concurrently
- **HTTP/WebSocket API** - RESTful endpoints + real-time WebSocket communication
- **Device management** - Track connected clients, push notifications
- **Bundle extensibility** - Add capabilities via hooks (input adapters, output channels)
- **Cross-device context** - Sessions can receive inputs from multiple devices

## Quick Start

```bash
# Install
uv pip install -e .

# Run server
amplifier-server run --port 8420

# With a bundle loaded on startup
amplifier-server run --bundle foundation
```

## CLI Commands

```bash
# Run server
amplifier-server run [--host HOST] [--port PORT] [--bundle BUNDLE]

# Check status
amplifier-server status [--server URL]

# List sessions
amplifier-server sessions [--server URL]

# List connected devices
amplifier-server devices [--server URL]

# Create a new session
amplifier-server create BUNDLE [--session-id ID]

# Execute a prompt
amplifier-server execute SESSION_ID "Your prompt here"

# Interactive chat
amplifier-server chat SESSION_ID
```

## API Endpoints

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions` | Create a new session |
| GET | `/sessions` | List all sessions |
| GET | `/sessions/{id}` | Get session info |
| POST | `/sessions/{id}/execute` | Execute a prompt |
| POST | `/sessions/{id}/inject` | Inject context |
| DELETE | `/sessions/{id}` | Stop session |

### Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/devices` | List connected devices |
| GET | `/devices/{id}` | Get device info |

### Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/notifications/ingest` | Receive notification from device |
| POST | `/notifications/push` | Push notification to device(s) |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws/device/{device_id}` | Device connection (notifications) |
| `/ws/chat/{session_id}` | Interactive chat with session |
| `/ws/events` | Event stream subscription |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AMPLIFIER APP SERVER                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Session Manager                            │   │
│  │                                                             │   │
│  │   Session "hub"         Session "work"        Session N     │   │
│  │   ├─ Bundle: foundation  ├─ Bundle: xyz       ├─ ...        │   │
│  │   └─ State: persistent   └─ State: ...        └─ ...        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Device Manager                             │   │
│  │                                                             │   │
│  │   Windows Client    Web Browser    Mobile App    CLI        │   │
│  │   (notifications)   (chat UI)      (push)        (chat)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Hook Registry                              │   │
│  │                                                             │   │
│  │   Input Hooks              Output Hooks                     │   │
│  │   ├─ NotificationInput     ├─ PushNotification             │   │
│  │   ├─ CalendarEvents        ├─ WebhookDelivery              │   │
│  │   └─ ScheduledTrigger      └─ EmailSender                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Extending with Bundles

Bundles can extend the server by providing hooks:

### Input Hooks

Inject external inputs into sessions:

```python
from amplifier_server.hooks import InputHook

class CalendarInputHook(InputHook):
    name = "calendar_input"
    
    async def start(self, server):
        self.server = server
        # Set up calendar API connection
    
    async def poll(self):
        # Return upcoming events
        return [
            {
                "content": "[CALENDAR] Meeting in 10 minutes: Design Review",
                "session_id": None,  # Default session
                "role": "user",
            }
        ]
    
    async def stop(self):
        pass
```

### Output Hooks

Process session outputs:

```python
from amplifier_server.hooks import OutputHook

class SlackOutputHook(OutputHook):
    name = "slack_output"
    
    async def start(self, server):
        self.server = server
        # Set up Slack client
    
    def should_handle(self, event, data):
        return event == "notification" and data.get("channel") == "slack"
    
    async def send(self, event, data):
        # Post to Slack
        return True
    
    async def stop(self):
        pass
```

## Configuration

Environment variables (prefix: `AMPLIFIER_SERVER_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AMPLIFIER_SERVER_HOST` | `0.0.0.0` | Host to bind to |
| `AMPLIFIER_SERVER_PORT` | `8420` | Port to listen on |
| `AMPLIFIER_SERVER_DATA_DIR` | `~/.amplifier-server` | Data directory |
| `AMPLIFIER_SERVER_DEFAULT_BUNDLE` | `foundation` | Default bundle |

Or use a config file:

```yaml
# config.yaml
host: "0.0.0.0"
port: 8420
data_dir: "~/.amplifier-server"
default_bundle: "foundation"
startup_bundles:
  - "foundation"
  - "attention-firewall"
```

## Use Cases

### Personal Hub

Always-on AI assistant that receives notifications from all your devices:

```bash
# On the server
amplifier-server run --bundle attention-firewall

# On Windows devices
attention-firewall client --server hub.tailnet:8420

# Chat from anywhere
amplifier-server chat personal-hub --server hub.tailnet:8420
```

### Team Bot

Shared AI assistant for a team:

```bash
amplifier-server run --bundle code-review --port 8420
# Team members connect via web UI or CLI
```

### Workflow Automation

Run recipes and workflows on a schedule:

```bash
amplifier-server run --bundle workflow-automation
# Scheduled hooks trigger at configured times
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Type check
pyright

# Format
ruff format
```

## License

MIT
