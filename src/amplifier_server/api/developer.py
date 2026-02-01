"""Developer API endpoints for testing and debugging."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager
from amplifier_server.notification_processor import NotificationProcessor
from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev", tags=["developer"])

# Track server start time for uptime
_server_start_time = time.time()

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


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    uptime_seconds: int
    llm_enabled: bool
    connected_devices: int
    notifications_today: int


class RecentDecision(BaseModel):
    """A recent LLM decision."""

    notification_id: int
    app_name: str | None
    title: str
    body_preview: str | None
    decision: str
    relevance_score: float | None
    rationale: str | None
    ai_thinking: str | None
    processing_time_ms: int | None
    timestamp: str


# Test scenarios with predefined content
TEST_SCENARIOS = {
    "vip_mention": {
        "app_name": "Microsoft Teams",
        "app_id": "com.microsoft.teams",
        "title": "Kevin Scott",
        "body": "Hey, can you join a quick call about the launch? Need your input.",
        "sender": "Kevin Scott",
        "conversation_type": "direct",
    },
    "urgent_keyword": {
        "app_name": "Outlook",
        "app_id": "com.microsoft.outlook",
        "title": "URGENT: Deadline Tomorrow",
        "body": "The review deadline is tomorrow at 5pm. Please submit ASAP.",
        "sender": "Project Manager",
        "conversation_type": "direct",
    },
    "group_chat": {
        "app_name": "WhatsApp",
        "app_id": "com.whatsapp",
        "title": "Family Group",
        "body": "~ Mom: Did everyone see the photos from last weekend?",
        "sender": "Family Group",
        "conversation_type": "group",
        "conversation_name": "Family Group",
    },
    "low_priority": {
        "app_name": "Slack",
        "app_id": "com.slack",
        "title": "#random",
        "body": "Check out this funny cat video!",
        "sender": "random-channel",
        "conversation_type": "channel",
        "conversation_name": "#random",
    },
    "action_needed": {
        "app_name": "GitHub",
        "app_id": "com.github.desktop",
        "title": "PR Review Requested",
        "body": "robotdad requested your review on PR #42: Fix critical auth bug",
        "sender": "GitHub",
        "conversation_type": "direct",
    },
    "calendar_reminder": {
        "app_name": "Calendar",
        "app_id": "com.microsoft.outlook.calendar",
        "title": "Meeting in 15 minutes",
        "body": "Design Review with the team - Conference Room A",
        "sender": "Calendar",
        "conversation_type": "direct",
    },
}


@router.get("/health", response_model=HealthResponse)
async def health_check(user: User = Depends(require_auth)) -> HealthResponse:
    """Get server health status with system information."""
    connected = 0
    today_count = 0

    if _device_manager:
        # list_devices(connected_only=True) returns only connected devices
        connected = len(_device_manager.list_devices(connected_only=True))

    if _notification_store:
        stats = await _notification_store.get_summary_stats()
        today_count = stats.get("today", 0)

    llm_enabled = _notification_processor is not None

    return HealthResponse(
        status="healthy",
        version="1.0.0",
        uptime_seconds=int(time.time() - _server_start_time),
        llm_enabled=llm_enabled,
        connected_devices=connected,
        notifications_today=today_count,
    )


@router.post("/test-notification", response_model=TestNotificationResponse)
async def send_test_notification(
    request: TestNotificationRequest,
    user: User = Depends(require_auth),
) -> TestNotificationResponse:
    """
    Send a test notification through the full processing pipeline.

    Use predefined scenarios or provide custom content.
    """
    if not _notification_store:
        raise HTTPException(status_code=503, detail="Notification store not available")

    # Build notification content from scenario or custom
    if request.scenario:
        if request.scenario not in TEST_SCENARIOS:
            available = list(TEST_SCENARIOS.keys())
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario '{request.scenario}'. Available: {available}",
            )
        content = TEST_SCENARIOS[request.scenario].copy()
    elif request.custom:
        content = {
            "app_name": request.custom.get("app_name", "Test App"),
            "app_id": request.custom.get("app_id", "test.app"),
            "title": request.custom.get("title", "Test Notification"),
            "body": request.custom.get("body", "Test from developer API."),
            "sender": request.custom.get("sender"),
            "conversation_type": request.custom.get("conversation_type"),
            "conversation_name": request.custom.get("conversation_name"),
        }
    else:
        content = {
            "app_name": "Cortex Dev",
            "app_id": "cortex.dev.test",
            "title": "Test Notification",
            "body": "Test from Cortex developer API. Push pipeline working!",
        }

    # Add required fields
    content["device_id"] = request.device_id
    content["timestamp"] = datetime.now(UTC).isoformat()

    try:
        # Create a simple request object for the store
        from amplifier_server.models import IngestNotificationRequest

        ingest_request = IngestNotificationRequest(
            device_id=request.device_id,
            app_id=content.get("app_id", "test.app"),
            app_name=content.get("app_name", "Test App"),
            title=content.get("title", "Test"),
            body=content.get("body"),
            timestamp=content["timestamp"],
            sender=content.get("sender"),
            conversation_type=content.get("conversation_type"),
            conversation_name=content.get("conversation_name"),
        )

        # Store the notification
        notification_id = await _notification_store.store(ingest_request)

        # Enqueue for processing and wait for result
        if _notification_processor:
            await _notification_processor.enqueue(notification_id)
            # Wait a bit for processing to complete
            await asyncio.sleep(3.0)

        # Fetch the result
        notif = await _notification_store.get_by_id(notification_id)
        if not notif:
            return TestNotificationResponse(
                notification_id=notification_id,
                decision="stored",
                pushed_to_device=False,
                error="Stored but could not retrieve result",
            )

        decision = notif.get("decision") or "pending"
        relevance_score = notif.get("relevance_score")
        rationale = notif.get("rationale")

        # Actually push to device if decision is "push"
        pushed = False
        if decision == "push" and _device_manager:
            from amplifier_server.models import PushNotificationRequest

            push_request = PushNotificationRequest(
                device_id=request.device_id,
                title=f"[TEST] {content.get('title', 'Test')}",
                body=content.get("body", "Test notification"),
                urgency="normal",
                rationale=rationale,
                app_source=content.get("app_name"),
            )
            results = await _device_manager.push_notification(push_request)
            # results is dict[device_id, success_bool]
            pushed = any(results.values()) if results else False
            logger.info(f"Test push results: {results}")

        return TestNotificationResponse(
            notification_id=notification_id,
            decision=decision,
            relevance_score=relevance_score,
            rationale=rationale,
            pushed_to_device=pushed,
        )

    except Exception as e:
        logger.error(f"Test notification failed: {e}")
        return TestNotificationResponse(
            decision="error",
            pushed_to_device=False,
            error=str(e),
        )


@router.get("/recent-decisions")
async def get_recent_decisions(
    limit: int = 10,
    user: User = Depends(require_auth),
) -> list[RecentDecision]:
    """Get recent LLM scoring decisions with full reasoning."""
    if not _notification_store:
        raise HTTPException(status_code=503, detail="Notification store not available")

    recent = await _notification_store.get_recent(limit=limit)

    decisions = []
    for notif in recent:
        body = notif.get("body", "")
        body_preview = body[:100] if body else None
        decisions.append(
            RecentDecision(
                notification_id=notif.get("id", 0),
                app_name=notif.get("app_name"),
                title=notif.get("title") or "",
                body_preview=body_preview,
                decision=notif.get("decision") or "pending",
                relevance_score=notif.get("relevance_score"),
                rationale=notif.get("rationale"),
                ai_thinking=notif.get("ai_thinking"),
                processing_time_ms=notif.get("processing_time_ms"),
                timestamp=notif.get("timestamp") or "",
            )
        )

    return decisions


@router.get("/config")
async def get_config(user: User = Depends(require_auth)) -> dict[str, Any]:
    """Get current notification processing configuration."""
    config: dict[str, Any] = {
        "llm_enabled": _notification_processor is not None,
        "vip_senders": [],
        "keywords": [],
        "push_threshold": 0.6,
        "focus_hours": [],
        "suppress_all_by_default": False,
    }

    if _notification_store:
        config["vip_senders"] = getattr(_notification_store, "vip_senders", [])
        config["keywords"] = getattr(_notification_store, "keywords", [])
        config["push_threshold"] = getattr(_notification_store, "push_threshold", 0.6)
        config["focus_hours"] = getattr(_notification_store, "focus_hours", [])

    return config


@router.get("/scenarios")
async def list_test_scenarios(
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """List available test scenarios with descriptions."""
    descriptions = {
        "vip_mention": "Message from a VIP sender with action request",
        "urgent_keyword": "Contains 'urgent' and 'deadline' keywords",
        "group_chat": "Casual group chat message (typically suppressed)",
        "low_priority": "Low relevance channel post (should suppress)",
        "action_needed": "PR review request requiring action",
        "calendar_reminder": "Calendar meeting reminder",
    }

    expected = {
        "vip_mention": "push (VIP + action request)",
        "urgent_keyword": "push (urgency + deadline)",
        "group_chat": "suppress (casual group chat)",
        "low_priority": "suppress (low relevance)",
        "action_needed": "push (explicit action needed)",
        "calendar_reminder": "push (time-sensitive)",
    }

    return {
        "scenarios": {
            name: {
                "description": descriptions.get(name, "Test scenario"),
                "expected_decision": expected.get(name, "varies"),
                "preview": {
                    "app_name": scenario["app_name"],
                    "title": scenario["title"],
                    "body_preview": (
                        scenario["body"][:50] + "..."
                        if len(scenario["body"]) > 50
                        else scenario["body"]
                    ),
                },
            }
            for name, scenario in TEST_SCENARIOS.items()
        }
    }


@router.get("/websocket-test")
async def websocket_test_info(
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Get information for testing WebSocket connections."""
    return {
        "websocket_url": "/ws/device/{device_id}",
        "protocol": "JSON messages over WebSocket",
        "authentication": {
            "method": "Send auth message after connecting",
            "example": {"type": "auth", "api_key": "your-api-key-here"},
        },
        "message_types": {
            "incoming": {
                "auth_success": "Authentication successful",
                "notification": "Push notification to display",
                "ping": "Keep-alive ping (respond with pong)",
            },
            "outgoing": {
                "auth": "Authentication request",
                "pong": "Response to ping",
            },
        },
        "example_python": """
import asyncio
import aiohttp
import json

async def test_websocket():
    async with aiohttp.ClientSession() as session:
        ws_url = "ws://server:19420/ws/device/test-device"
        async with session.ws_connect(ws_url) as ws:
            await ws.send_json({"type": "auth", "api_key": "your-key"})

            async for msg in ws:
                data = json.loads(msg.data)
                print(f"Received: {data}")

                if data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

asyncio.run(test_websocket())
""",
    }
