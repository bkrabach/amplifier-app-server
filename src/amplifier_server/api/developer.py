"""Developer API endpoints for testing and debugging.

These endpoints are specifically for development and testing purposes.
General-purpose endpoints have been moved to their respective modules:
- /status - Server health and status
- /config - Configuration settings
- /connections - WebSocket connection status
- /notifications/decisions - LLM decision history
- /devices/{id}/ping - Device connectivity testing
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager
from amplifier_server.models import IngestNotificationRequest
from amplifier_server.notification_processor import NotificationProcessor
from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev", tags=["developer"])

# Module-level storage for injected managers
_notification_store: NotificationStore | None = None
_notification_processor: NotificationProcessor | None = None
_device_manager: DeviceManager | None = None


def inject_managers(
    notification_store: NotificationStore | None = None,
    notification_processor: NotificationProcessor | None = None,
    device_manager: DeviceManager | None = None,
) -> None:
    """Inject managers into this module."""
    global _notification_store, _notification_processor, _device_manager
    _notification_store = notification_store
    _notification_processor = notification_processor
    _device_manager = device_manager


class TestNotificationRequest(BaseModel):
    """Request to send a test notification."""

    device_id: str
    scenario: str | None = None
    custom: dict[str, Any] | None = None


class TestNotificationResponse(BaseModel):
    """Response from test notification."""

    notification_id: int | None = None
    decision: str
    relevance_score: float | None = None
    rationale: str | None = None
    pushed_to_device: bool
    error: str | None = None


# Test scenarios for development
TEST_SCENARIOS: dict[str, dict[str, Any]] = {
    "vip_mention": {
        "app_name": "Microsoft Teams",
        "title": "Kevin Scott",
        "body": "Hey, can you join a quick call about the launch? Need your input.",
        "expected": "push (VIP sender + action request)",
    },
    "urgent_keyword": {
        "app_name": "Microsoft Outlook",
        "title": "URGENT: Production Issue",
        "body": "We have a regression in the deployment pipeline. Need immediate attention.",
        "expected": "push (urgent keyword + action required)",
    },
    "routine_chat": {
        "app_name": "WhatsApp",
        "title": "Family Group",
        "body": "Anyone want to get dinner tonight?",
        "expected": "summarize (routine message, no urgency)",
    },
    "calendar_reminder": {
        "app_name": "Microsoft Outlook",
        "title": "Reminder: Team Standup in 15 minutes",
        "body": "Your meeting 'Team Standup' starts at 10:00 AM.",
        "expected": "push (time-sensitive)",
    },
}


@router.post("/test-notification", response_model=TestNotificationResponse)
async def send_test_notification(
    request: TestNotificationRequest,
    user: User = Depends(require_auth),
) -> TestNotificationResponse:
    """
    Send a test notification through the processing pipeline.

    Use predefined scenarios or custom content to test how the AI
    scores and routes notifications. The notification will be stored
    and processed, and if the decision is 'push', it will be sent
    to the specified device.

    Scenarios: vip_mention, urgent_keyword, routine_chat, calendar_reminder
    """
    if not _notification_store or not _notification_processor:
        raise HTTPException(
            status_code=503,
            detail="Notification processing not available",
        )

    # Get notification content
    if request.scenario and request.scenario in TEST_SCENARIOS:
        content = TEST_SCENARIOS[request.scenario].copy()
    elif request.custom:
        content = request.custom
    else:
        content = {
            "app_name": "Cortex Dev",
            "title": "[TEST] Test Notification",
            "body": "This is a test notification from the developer API.",
        }

    # Add test prefix to title if not already present
    if not content.get("title", "").startswith("[TEST]"):
        content["title"] = f"[TEST] {content.get('title', 'Test')}"

    # Store the notification
    ingest_request = IngestNotificationRequest(
        device_id=request.device_id,
        app_id=content.get("app_id", "cortex.dev.test"),
        app_name=content.get("app_name", "Cortex Dev"),
        title=content.get("title", "Test"),
        body=content.get("body", ""),
        timestamp=datetime.now(UTC).isoformat(),
    )
    notification_id = await _notification_store.store(ingest_request)

    # Process it
    await _notification_processor.enqueue(notification_id)

    # Wait for processing (with timeout)
    max_wait = 5.0
    poll_interval = 0.2
    elapsed = 0.0

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        notif = await _notification_store.get_by_id(notification_id)
        if notif and notif.get("decision"):
            break

    # Fetch final result
    notif = await _notification_store.get_by_id(notification_id)
    if not notif:
        return TestNotificationResponse(
            notification_id=notification_id,
            decision="error",
            pushed_to_device=False,
            error="Notification not found after processing",
        )

    decision = notif.get("decision") or "pending"
    score = notif.get("relevance_score")
    rationale = notif.get("rationale")

    # If decision is push, actually push to device
    pushed = False
    if decision == "push" and _device_manager:
        from amplifier_server.models import PushNotificationRequest

        push_request = PushNotificationRequest(
            device_id=request.device_id,
            title=f"🔔 {content.get('title', 'Test')}",
            body=content.get("body", ""),
            urgency="high" if score and score >= 0.7 else "normal",
            rationale=rationale,
            app_source=content.get("app_name"),
        )

        results = await _device_manager.push_notification(push_request)
        pushed = results.get(request.device_id, False)
        logger.info(f"Test push results: {results}")

    return TestNotificationResponse(
        notification_id=notification_id,
        decision=decision,
        relevance_score=score,
        rationale=rationale,
        pushed_to_device=pushed,
    )


@router.get("/scenarios")
async def get_test_scenarios(
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """
    List available test scenarios.

    Returns predefined test scenarios that can be used with
    POST /dev/test-notification to test notification processing.
    """
    scenarios = {}
    for name, content in TEST_SCENARIOS.items():
        scenarios[name] = {
            "app_name": content.get("app_name"),
            "title": content.get("title"),
            "body_preview": content.get("body", "")[:50] + "...",
            "expected_behavior": content.get("expected"),
        }

    return {
        "scenarios": scenarios,
        "usage": "POST /dev/test-notification with {device_id, scenario: 'name'}",
    }


@router.get("/websocket-test")
async def get_websocket_test_info(
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """
    Get WebSocket testing information and example code.

    Returns connection instructions and example code for testing
    WebSocket connectivity from client applications.
    """
    return {
        "endpoint": "/ws/device/{device_id}",
        "auth_message": {"type": "auth", "api_key": "your-api-key"},
        "message_types": {
            "notification": "Push notification to display",
            "ping": "Connectivity test (respond with pong)",
            "config_update": "Configuration changed",
        },
        "example_python": """
import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:19420/ws/device/my-device-id"
    async with websockets.connect(uri) as ws:
        # Authenticate
        await ws.send_json({"type": "auth", "api_key": "your-key"})
        
        # Listen for messages
        async for msg in ws:
            data = json.loads(msg)
            print(f"Received: {data['type']}")
            
            if data["type"] == "ping":
                await ws.send_json({"type": "pong"})

asyncio.run(test_websocket())
""",
    }
