"""Developer API endpoints for testing and debugging."""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from ..notifications import NotificationStore, DeviceRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dev", tags=["developer"])

# Track server start time for uptime
_server_start_time = time.time()


class TestNotificationRequest(BaseModel):
    """Request to send a test notification."""
    device_id: str
    scenario: str | None = None  # Predefined test scenario
    custom: dict[str, Any] | None = None  # Custom notification content


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
        "body": "Hey, can you join a quick call about the launch? Need your input on the timeline.",
        "sender": "Kevin Scott",
        "conversation_type": "direct",
    },
    "urgent_keyword": {
        "app_name": "Outlook",
        "app_id": "com.microsoft.outlook",
        "title": "URGENT: Deadline Tomorrow",
        "body": "The review deadline is tomorrow at 5pm. Please submit your changes ASAP.",
        "sender": "Project Manager",
        "conversation_type": "direct",
    },
    "group_chat": {
        "app_name": "WhatsApp",
        "app_id": "com.whatsapp",
        "title": "Family Group",
        "body": "~ Mom: Did everyone see the photos from last weekend? 😊",
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


def _get_notification_store() -> NotificationStore:
    """Get the notification store instance."""
    from ..server import get_notification_store
    return get_notification_store()


def _get_device_registry() -> DeviceRegistry:
    """Get the device registry instance."""
    from ..server import get_device_registry
    return get_device_registry()


@router.get("/health", response_model=HealthResponse)
async def health_check(user: dict = Depends(get_current_user)):
    """Get server health status with system information."""
    store = _get_notification_store()
    registry = _get_device_registry()
    
    # Count today's notifications
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stats = store.get_stats()
    
    # Check if LLM is enabled
    llm_enabled = store.llm_enabled if hasattr(store, 'llm_enabled') else True
    
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        uptime_seconds=int(time.time() - _server_start_time),
        llm_enabled=llm_enabled,
        connected_devices=len(registry.get_all_devices()),
        notifications_today=stats.get("today", 0),
    )


@router.post("/test-notification", response_model=TestNotificationResponse)
async def send_test_notification(
    request: TestNotificationRequest,
    user: dict = Depends(get_current_user)
):
    """
    Send a test notification through the full processing pipeline.
    
    This endpoint allows testing:
    1. Notification ingestion
    2. LLM scoring (if enabled)
    3. Push delivery to device
    
    Use predefined scenarios or provide custom content.
    """
    store = _get_notification_store()
    registry = _get_device_registry()
    
    # Build notification content
    if request.scenario:
        if request.scenario not in TEST_SCENARIOS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario '{request.scenario}'. Available: {list(TEST_SCENARIOS.keys())}"
            )
        content = TEST_SCENARIOS[request.scenario].copy()
    elif request.custom:
        content = {
            "app_name": request.custom.get("app_name", "Test App"),
            "app_id": request.custom.get("app_id", "test.app"),
            "title": request.custom.get("title", "Test Notification"),
            "body": request.custom.get("body", "This is a test notification from the developer API."),
            "sender": request.custom.get("sender"),
            "conversation_type": request.custom.get("conversation_type"),
            "conversation_name": request.custom.get("conversation_name"),
        }
    else:
        # Default test notification
        content = {
            "app_name": "Cortex Dev",
            "app_id": "cortex.dev.test",
            "title": "Test Notification",
            "body": "This is a test notification from the Cortex developer API. If you see this, the push pipeline is working!",
        }
    
    # Add metadata
    content["device_id"] = request.device_id
    content["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    try:
        # Process through the notification pipeline
        result = await store.add_notification(content)
        
        notification_id = result.get("id")
        decision = result.get("decision", "unknown")
        relevance_score = result.get("relevance_score")
        rationale = result.get("rationale")
        
        # Check if push was delivered
        pushed = False
        if decision == "push":
            device = registry.get_device(request.device_id)
            if device and device.get("connected"):
                # The notification should have been pushed during add_notification
                pushed = True
        
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
    user: dict = Depends(get_current_user)
) -> list[RecentDecision]:
    """
    Get recent LLM scoring decisions with full reasoning.
    
    Useful for debugging why notifications were pushed or suppressed.
    """
    store = _get_notification_store()
    
    # Get recent notifications with their decisions
    recent = store.get_recent(limit=limit)
    
    decisions = []
    for notif in recent:
        decisions.append(RecentDecision(
            notification_id=notif.get("id", 0),
            app_name=notif.get("app_name"),
            title=notif.get("title", ""),
            body_preview=notif.get("body", "")[:100] if notif.get("body") else None,
            decision=notif.get("decision", "unknown"),
            relevance_score=notif.get("relevance_score"),
            rationale=notif.get("rationale"),
            ai_thinking=notif.get("ai_thinking"),
            processing_time_ms=notif.get("processing_time_ms"),
            timestamp=notif.get("timestamp", ""),
        ))
    
    return decisions


@router.get("/config")
async def get_config(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Get current notification processing configuration.
    
    Shows VIP senders, keywords, thresholds, and focus hours.
    """
    store = _get_notification_store()
    
    # Get configuration from store
    config = {
        "llm_enabled": getattr(store, 'llm_enabled', True),
        "vip_senders": getattr(store, 'vip_senders', []),
        "keywords": getattr(store, 'keywords', []),
        "push_threshold": getattr(store, 'push_threshold', 0.6),
        "focus_hours": getattr(store, 'focus_hours', []),
        "suppress_all_by_default": getattr(store, 'suppress_all', False),
    }
    
    return config


@router.get("/scenarios")
async def list_test_scenarios(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    List available test scenarios with descriptions.
    
    Use these with POST /dev/test-notification.
    """
    return {
        "scenarios": {
            name: {
                "description": _get_scenario_description(name),
                "expected_decision": _get_expected_decision(name),
                "preview": {
                    "app_name": scenario["app_name"],
                    "title": scenario["title"],
                    "body_preview": scenario["body"][:50] + "..." if len(scenario["body"]) > 50 else scenario["body"],
                }
            }
            for name, scenario in TEST_SCENARIOS.items()
        }
    }


def _get_scenario_description(name: str) -> str:
    """Get description for a test scenario."""
    descriptions = {
        "vip_mention": "Message from a VIP sender (Kevin Scott) with action request",
        "urgent_keyword": "Contains 'urgent' and 'deadline' keywords",
        "group_chat": "Casual group chat message (typically suppressed)",
        "low_priority": "Low relevance channel post (should suppress)",
        "action_needed": "PR review request requiring action",
        "calendar_reminder": "Calendar meeting reminder",
    }
    return descriptions.get(name, "Test scenario")


def _get_expected_decision(name: str) -> str:
    """Get expected decision for a test scenario."""
    expected = {
        "vip_mention": "push (VIP + action request)",
        "urgent_keyword": "push (urgency + deadline)",
        "group_chat": "suppress (casual group chat)",
        "low_priority": "suppress (low relevance)",
        "action_needed": "push (explicit action needed)",
        "calendar_reminder": "push (time-sensitive)",
    }
    return expected.get(name, "varies")


@router.get("/websocket-test")
async def websocket_test_info(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Get information for testing WebSocket connections.
    
    Returns example code and connection URLs.
    """
    return {
        "websocket_url": "/ws/device/{device_id}",
        "protocol": "JSON messages over WebSocket",
        "authentication": {
            "method": "Send auth message after connecting",
            "example": {"type": "auth", "api_key": "your-api-key-here"}
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
            }
        },
        "example_python": '''
import asyncio
import aiohttp
import json

async def test_websocket():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("ws://server:19420/ws/device/test-device") as ws:
            # Authenticate
            await ws.send_json({"type": "auth", "api_key": "your-key"})
            
            async for msg in ws:
                data = json.loads(msg.data)
                print(f"Received: {data}")
                
                if data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

asyncio.run(test_websocket())
''',
        "example_javascript": '''
const ws = new WebSocket("ws://server:19420/ws/device/test-device");

ws.onopen = () => {
    ws.send(JSON.stringify({type: "auth", api_key: "your-key"}));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log("Received:", data);
    
    if (data.type === "ping") {
        ws.send(JSON.stringify({type: "pong"}));
    } else if (data.type === "notification") {
        // Show notification to user
        new Notification(data.title, {body: data.body});
    }
};
'''
    }
