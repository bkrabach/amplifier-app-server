# Cortex Hub Developer Guide

This guide is for developers building clients (Windows, macOS, Android, etc.) that connect to the Cortex Hub server.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CORTEX HUB (Server)                            │
│                      Default: http://your-server:19420              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Notification    │  │  LLM Scoring     │  │  Device          │  │
│  │  Ingestion       │  │  (Amplifier)     │  │  Registry        │  │
│  │  POST /notify/*  │  │  Relevance 0-1   │  │  WebSocket       │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Triage Center   │  │  Chat (Cortex)   │  │  Auth & Admin    │  │
│  │  GET /triage/*   │  │  WS /chat/cortex │  │  /auth, /admin   │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │   Windows   │     │    macOS    │     │   Android   │
   │   Client    │     │   Client    │     │   Client    │
   └─────────────┘     └─────────────┘     └─────────────┘
```

## Quick Start for Client Developers

### 1. Get an API Key

```bash
# Option A: Use the web UI
# Go to http://your-server:19420 → Login → Profile → Generate API Key

# Option B: Use the CLI (if you have access to the server)
curl -X POST "http://your-server:19420/admin/users/{user_id}/api-keys" \
  -H "Authorization: Bearer {admin_token}" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-macos-client"}'
```

### 2. Store the API Key

Create `~/.cortex/client.yaml`:
```yaml
server_url: "http://your-server:19420"
api_key: "your-api-key-here"
device_id: "my-mac-001"  # Unique identifier for this device
```

### 3. Connect and Send Notifications

See the API Reference below for detailed endpoint documentation.

---

## API Reference

### Authentication

All API requests require one of:
- **Header**: `X-API-Key: your-api-key`
- **Header**: `Authorization: Bearer your-jwt-token`

### Core Endpoints

#### POST /notifications/ingest
**Ingest a notification from a client device.**

```json
// Request
{
  "device_id": "my-mac-001",
  "app_id": "com.apple.MobileSMS",
  "app_name": "Messages",
  "title": "John Doe",
  "body": "Hey, are you free for lunch?",
  "timestamp": "2026-02-01T10:30:00Z",
  
  // Optional enriched fields (highly recommended)
  "app_display_name": "Messages",
  "app_package_id": "com.apple.MobileSMS",
  "conversation_type": "direct",      // "direct" | "group" | "channel"
  "conversation_name": "John Doe",    // Group/channel name if applicable
  "sender": "John Doe",
  "extras": {}                        // Platform-specific metadata
}

// Response
{
  "status": "received",
  "notification_id": 123,
  "decision": "push",                 // "push" | "suppress" | "summarize"
  "relevance_score": 0.85,
  "rationale": "Direct message from contact, question detected"
}
```

**Decision Values:**
- `push` - Show notification to user immediately
- `suppress` - Don't show, but store for digest
- `summarize` - Add to hourly/daily summary

#### GET /notifications/recent
**Get recent notifications (for debugging/testing).**

```bash
curl "http://server:19420/notifications/recent?limit=10" \
  -H "X-API-Key: your-key"
```

#### GET /notifications/stats
**Get notification statistics.**

```json
{
  "total": 1523,
  "today": 47,
  "pushed": 12,
  "suppressed": 35
}
```

#### POST /notifications/push
**Manually push a notification to a device (for testing).**

```json
// Request
{
  "device_id": "my-mac-001",
  "title": "Test from Cortex",
  "body": "This is a test notification",
  "source": "test"
}

// Response
{
  "status": "pushed",
  "device_id": "my-mac-001"
}
```

### Device Management

#### WebSocket /ws/device/{device_id}
**Real-time connection for receiving push notifications.**

```javascript
// Connect
const ws = new WebSocket('ws://server:19420/ws/device/my-mac-001');

// Authenticate immediately after connecting
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'auth',
    api_key: 'your-api-key'
  }));
};

// Handle incoming messages
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch (msg.type) {
    case 'auth_success':
      console.log('Connected and authenticated');
      break;
      
    case 'notification':
      // Display this notification to the user
      showNotification(msg.title, msg.body, msg.source);
      break;
      
    case 'ping':
      ws.send(JSON.stringify({ type: 'pong' }));
      break;
  }
};
```

#### GET /devices
**List all connected devices.**

```json
[
  {
    "device_id": "windows-desktop-001",
    "platform": "windows",
    "connected": true,
    "last_seen": "2026-02-01T10:30:00Z"
  },
  {
    "device_id": "my-mac-001", 
    "platform": "macos",
    "connected": true,
    "last_seen": "2026-02-01T10:31:00Z"
  }
]
```

### Status & Configuration Endpoints

#### GET /status
**Server health and status information.**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "llm_enabled": true,
  "connected_devices": 2,
  "notifications_today": 47
}
```

#### GET /config
**View current notification processing configuration.**

```json
{
  "llm_enabled": true,
  "vip_senders": ["Kevin Scott", "Sam Schillace"],
  "keywords": ["urgent", "deadline", "launch"],
  "push_threshold": 0.6,
  "focus_hours": ["09:00-12:00", "13:00-16:00"]
}
```

#### GET /connections
**View all WebSocket connections and their status.**

Use this to verify device connectivity - check if your client's device_id matches what the server sees.

```json
{
  "total_devices": 2,
  "connected_count": 1,
  "connections": [
    {
      "device_id": "macbook-pro-123",
      "device_name": "MacBook Pro",
      "platform": "macos",
      "connected": true,
      "connected_at": "2026-02-01T08:00:00",
      "last_seen": "2026-02-01T09:10:00"
    }
  ],
  "troubleshooting": {
    "no_devices": "Connect via WebSocket to /ws/device/{your-device-id}",
    "device_not_receiving": "Ensure notification device_id matches a connected device_id exactly",
    "wrong_device_id": "The device_id in requests must match your WebSocket connection"
  }
}
```

### Notification Insights

#### GET /notifications/decisions
**See recent LLM scoring decisions with full reasoning.**

Useful for understanding why you did or didn't receive a notification.

```json
[
  {
    "notification_id": 123,
    "app_name": "WhatsApp",
    "title": "Family Group",
    "decision": "suppress",
    "relevance_score": 0.25,
    "rationale": "Group chat, casual conversation, no mentions or actions",
    "ai_thinking": "Looking at this notification...[full reasoning]",
    "processing_time_ms": 1250
  }
]
```

### Device Management

#### POST /devices/{device_id}/ping
**Send a test ping to verify device connectivity.**

The device will receive a WebSocket message with `type: "ping"`. Use this to verify the connection before testing notifications.

```json
// Response (success)
{
  "success": true,
  "device_id": "macbook-pro-123",
  "message_sent": {
    "type": "ping",
    "payload": {"test": true, "message": "Connectivity test"}
  },
  "note": "Device should respond with type='pong' if working correctly"
}

// Response (not connected)
{
  "success": false,
  "error": "Device 'macbook-pro-123' is not connected",
  "hint": "Check /connections to see connected device_ids"
}
```

### Developer/Testing Endpoints

These endpoints are specifically for development and testing.

#### POST /dev/test-notification
**Send a test notification through the full pipeline.**

```json
// Request
{
  "device_id": "my-mac-001",    // Target device to receive the push
  "scenario": "vip_mention",     // Test scenario (see below)
  "custom": {                    // Or provide custom content
    "app_name": "Test App",
    "title": "Test Title",
    "body": "Test body content"
  }
}

// Response
{
  "notification_id": 456,
  "decision": "push",
  "relevance_score": 0.92,
  "rationale": "VIP sender detected",
  "pushed_to_device": true
}
```

**Test Scenarios:**
- `vip_mention` - Simulates a message from a VIP sender
- `urgent_keyword` - Contains urgent/deadline keywords
- `routine_chat` - Routine chat message (typically summarized)
- `calendar_reminder` - Time-sensitive calendar reminder

#### GET /dev/scenarios
**List available test scenarios with expected behaviors.**

#### GET /dev/websocket-test
**Get WebSocket testing instructions and example code.**

### Log Access

#### GET /logs
**Get recent server log entries.**

Useful for debugging without SSH access. Supports filtering by level and component.

```bash
# Get last 100 log entries
GET /logs

# Filter by level
GET /logs?level=ERROR

# Filter by component
GET /logs?component=notification_processor

# Combine filters with limit
GET /logs?level=WARNING&component=triage&limit=50
```

```json
{
  "count": 25,
  "entries": [
    {
      "timestamp": "2026-02-01T13:45:00Z",
      "level": "INFO",
      "logger": "amplifier_server.notification_processor",
      "component": "notification_processor",
      "message": "Processing notification 123 for device macbook-001"
    }
  ],
  "filters": {"level": null, "component": null},
  "hint": "Use /logs/stream for real-time streaming via WebSocket"
}
```

**Components:** `notification_processor`, `device_manager`, `triage`, `auth`, `websocket`, etc.

#### WebSocket /logs/stream
**Stream logs in real-time.**

Connect via WebSocket for live log streaming. Useful for monitoring during development or debugging live issues.

```javascript
// Connect to log stream
const ws = new WebSocket('ws://localhost:19420/logs/stream');

// Authenticate first
ws.onopen = () => {
  ws.send(JSON.stringify({ type: 'auth', api_key: 'your-api-key' }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'authenticated') {
    console.log('Connected to log stream');
  } else if (data.type === 'log') {
    const entry = data.entry;
    console.log(`[${entry.level}] ${entry.component}: ${entry.message}`);
  }
};
```

**Query parameters:**
- `level` - Filter by log level (INFO, WARNING, ERROR)
- `component` - Filter by component name

**Message types received:**
- `{"type": "authenticated", "user": "..."}` - Auth successful
- `{"type": "log", "entry": {...}}` - Log entry (real-time)
- `{"type": "log", "backfill": true, "entry": {...}}` - Historical entry (on connect)
- `{"type": "error", "message": "..."}` - Error message

```bash
curl -X POST "http://server:19420/dev/ping-device?device_id=macbook-pro-123" \
  -H "X-API-Key: your-key"
```

Response:
```json
{
  "success": true,
  "device_id": "macbook-pro-123",
  "message_sent": {
    "type": "ping",
    "payload": {"test": true, "message": "Connectivity test from /dev/ping-device"}
  },
  "note": "Device should respond with type='pong' if working correctly"
}
```

The device will receive a WebSocket message with `type: "ping"`. Use this to verify the WebSocket connection is working before testing notifications.

---

## Building a Client

### Required Capabilities

1. **Notification Listener** - Capture OS notifications
2. **HTTP Client** - POST notifications to server
3. **WebSocket Client** - Receive push notifications
4. **Local Notification Display** - Show pushed notifications
5. **Configuration Storage** - Store API key and settings

### Platform-Specific Notes

#### macOS

```swift
// Capture notifications using UNUserNotificationCenter
// Note: macOS requires app to be in Notification Center to capture others' notifications
// Alternative: Use Notification Center history API

// Display notifications
let content = UNMutableNotificationContent()
content.title = "Cortex"
content.body = message
let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
UNUserNotificationCenter.current().add(request)
```

#### Windows

```python
# Use pywinrt to capture notifications
from winrt.windows.ui.notifications.management import UserNotificationListener

listener = UserNotificationListener.current
notifications = await listener.get_notifications_async(...)
```

### Recommended Client Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT STARTUP                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Load config     │
                    │ (~/.cortex/     │
                    │  client.yaml)   │
                    └────────┬────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │ Connect WS      │             │ Start notif     │
    │ for push recv   │             │ listener        │
    └────────┬────────┘             └────────┬────────┘
              │                               │
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │ On WS message:  │             │ On notification:│
    │ show notif      │             │ POST to server  │
    └─────────────────┘             └─────────────────┘
```

---

## Debugging Tips

### 1. Test Your Connection

```bash
# Check server health
curl http://server:19420/dev/health

# List your devices
curl -H "X-API-Key: your-key" http://server:19420/devices
```

### 2. Send a Test Notification

```bash
# Send through full pipeline
curl -X POST http://server:19420/dev/test-notification \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "my-mac-001", "scenario": "vip_mention"}'
```

### 3. Check Recent Decisions

```bash
# See what the LLM decided
curl -H "X-API-Key: your-key" http://server:19420/dev/recent-decisions?limit=5
```

### 4. Verify WebSocket Connection

```python
import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://server:19420/ws/device/test-device"
    async with websockets.connect(uri) as ws:
        # Authenticate
        await ws.send(json.dumps({"type": "auth", "api_key": "your-key"}))
        response = await ws.recv()
        print(f"Auth response: {response}")
        
        # Wait for notifications
        while True:
            msg = await ws.recv()
            print(f"Received: {msg}")

asyncio.run(test_ws())
```

### 5. Check Server Logs

The server logs all incoming notifications and decisions. Look for:
- `[RAW NOTIFICATION]` - What was received
- `[LLM DECISION]` - What the AI decided
- `[PUSH]` - What was sent to devices

---

## Common Issues

### "Notification not appearing on device"

1. Check WebSocket is connected: `GET /devices`
2. Verify the decision was "push": `GET /dev/recent-decisions`
3. Check device_id matches in both ingest and WebSocket

### "All notifications being suppressed"

1. Check LLM is enabled: `GET /dev/config`
2. Try a VIP sender or urgent keyword
3. Check `relevance_score` - threshold is typically 0.6

### "WebSocket disconnects frequently"

1. Implement reconnection logic with exponential backoff
2. Respond to `ping` messages with `pong`
3. Check network stability

### "Slow notification processing"

1. LLM scoring takes ~1-3 seconds
2. First notification may be slower (model warming up)
3. Check `processing_time_ms` in recent decisions

---

## Example: Minimal Python Client

```python
#!/usr/bin/env python3
"""Minimal Cortex client example."""

import asyncio
import json
import aiohttp
import yaml
from pathlib import Path

class CortexClient:
    def __init__(self):
        config_path = Path.home() / ".cortex" / "client.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        self.server_url = config["server_url"]
        self.api_key = config["api_key"]
        self.device_id = config.get("device_id", "python-client")
        self.headers = {"X-API-Key": self.api_key}
    
    async def send_notification(self, app_name: str, title: str, body: str):
        """Send a notification to the server."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "device_id": self.device_id,
                "app_id": app_name.lower().replace(" ", "."),
                "app_name": app_name,
                "title": title,
                "body": body,
            }
            async with session.post(
                f"{self.server_url}/notifications/ingest",
                json=payload,
                headers=self.headers
            ) as resp:
                return await resp.json()
    
    async def listen_for_pushes(self, on_notification):
        """Connect to WebSocket and listen for push notifications."""
        ws_url = self.server_url.replace("http", "ws")
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                f"{ws_url}/ws/device/{self.device_id}"
            ) as ws:
                # Authenticate
                await ws.send_json({"type": "auth", "api_key": self.api_key})
                
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "notification":
                            await on_notification(data)
                        elif data.get("type") == "ping":
                            await ws.send_json({"type": "pong"})

# Usage
async def main():
    client = CortexClient()
    
    # Send a test notification
    result = await client.send_notification(
        app_name="Test App",
        title="Hello",
        body="This is a test"
    )
    print(f"Decision: {result['decision']}, Score: {result.get('relevance_score')}")
    
    # Listen for pushes
    async def on_push(notif):
        print(f"PUSH: {notif['title']} - {notif['body']}")
    
    await client.listen_for_pushes(on_push)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Need Help?

- Check `/dev/health` for server status
- Check `/dev/recent-decisions` for LLM reasoning
- Server logs contain detailed debugging info
- Use test scenarios to verify end-to-end flow
