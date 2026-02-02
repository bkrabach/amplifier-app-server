"""Configuration and notification rules API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from amplifier_server.auth import User, require_auth
from amplifier_server.notification_processor import NotificationProcessor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

# Module-level storage for injected managers
_notification_processor: NotificationProcessor | None = None


def inject_managers(
    notification_processor: NotificationProcessor | None = None,
) -> None:
    """Inject managers into this module."""
    global _notification_processor
    _notification_processor = notification_processor


def _get_processor() -> NotificationProcessor:
    """Get notification processor or raise 503."""
    if not _notification_processor:
        raise HTTPException(status_code=503, detail="Configuration not available")
    return _notification_processor


# =============================================================================
# Request/Response Models
# =============================================================================


class AddItemRequest(BaseModel):
    """Request to add an item to a list."""

    value: str = Field(description="The value to add")


class RemoveItemRequest(BaseModel):
    """Request to remove an item from a list."""

    value: str = Field(description="The value to remove")


class UpdateThresholdRequest(BaseModel):
    """Request to update the push threshold."""

    threshold: float = Field(ge=0.0, le=1.0, description="New threshold (0.0-1.0)")


class AppRuleRequest(BaseModel):
    """Request to set an app's priority rule."""

    app_name: str = Field(description="App name (e.g., 'Microsoft Teams')")
    priority: str = Field(description="Priority level: 'high', 'normal', 'low'")


# =============================================================================
# General Configuration
# =============================================================================


@router.get("/config")
async def get_config(user: User = Depends(require_auth)) -> dict[str, Any]:
    """
    Get current notification processing configuration.

    Returns VIP senders, keywords, thresholds, and other settings
    that control how notifications are scored and routed.
    """
    processor = _get_processor()
    config = processor.config

    return {
        "llm_enabled": processor.use_llm,
        "vip_senders": list(config.vip_senders),
        "keywords": {
            "urgent": list(config.urgent_keywords),
            "action": list(config.action_keywords),
        },
        "apps": {
            "priority": list(config.priority_apps),
            "low_priority": list(config.low_priority_apps),
        },
        "push_threshold": config.push_threshold,
        "user_aliases": list(config.user_aliases),
    }


@router.get("/config/notification-rules")
async def get_notification_rules(user: User = Depends(require_auth)) -> dict[str, Any]:
    """
    Get all notification rules in a structured format.

    This endpoint is designed for UI consumption, providing all
    configurable rules in one request.
    """
    processor = _get_processor()
    config = processor.config

    return {
        "vips": {
            "items": list(config.vip_senders),
            "count": len(config.vip_senders),
            "description": "Messages from VIP senders always get pushed through",
        },
        "keywords": {
            "urgent": {
                "items": list(config.urgent_keywords),
                "count": len(config.urgent_keywords),
                "description": "Keywords that indicate urgency",
            },
            "action": {
                "items": list(config.action_keywords),
                "count": len(config.action_keywords),
                "description": "Keywords that indicate action is needed",
            },
        },
        "apps": {
            "priority": {
                "items": list(config.priority_apps),
                "count": len(config.priority_apps),
                "description": "Apps that get higher priority scoring",
            },
            "low_priority": {
                "items": list(config.low_priority_apps),
                "count": len(config.low_priority_apps),
                "description": "Apps that get lower priority (stored but rarely pushed)",
            },
        },
        "thresholds": {
            "push": config.push_threshold,
            "description": f"Notifications scoring above {config.push_threshold} get pushed",
        },
        "user_aliases": {
            "items": list(config.user_aliases),
            "count": len(config.user_aliases),
            "description": "Names/aliases to detect when you're mentioned",
        },
    }


# =============================================================================
# VIP Management
# =============================================================================


@router.get("/config/vips")
async def list_vips(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List all VIP senders."""
    processor = _get_processor()
    return {
        "vips": list(processor.config.vip_senders),
        "count": len(processor.config.vip_senders),
    }


@router.post("/config/vips")
async def add_vip(
    request: AddItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Add a VIP sender."""
    processor = _get_processor()
    name = request.value.strip()

    if not name:
        raise HTTPException(status_code=400, detail="VIP name cannot be empty")

    if name in processor.config.vip_senders:
        return {"status": "already_exists", "vip": name}

    processor.config.vip_senders.append(name)
    logger.info(f"Added VIP: {name} (by {user.username})")

    return {
        "status": "added",
        "vip": name,
        "total_vips": len(processor.config.vip_senders),
    }


@router.delete("/config/vips")
async def remove_vip(
    request: RemoveItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Remove a VIP sender."""
    processor = _get_processor()
    name = request.value.strip()

    if name not in processor.config.vip_senders:
        raise HTTPException(status_code=404, detail=f"VIP '{name}' not found")

    processor.config.vip_senders.remove(name)
    logger.info(f"Removed VIP: {name} (by {user.username})")

    return {
        "status": "removed",
        "vip": name,
        "total_vips": len(processor.config.vip_senders),
    }


# =============================================================================
# Keyword Management
# =============================================================================


@router.get("/config/keywords")
async def list_keywords(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List all keywords (urgent and action)."""
    processor = _get_processor()
    return {
        "urgent": list(processor.config.urgent_keywords),
        "action": list(processor.config.action_keywords),
        "counts": {
            "urgent": len(processor.config.urgent_keywords),
            "action": len(processor.config.action_keywords),
        },
    }


@router.get("/config/keywords/urgent")
async def list_urgent_keywords(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List urgent keywords."""
    processor = _get_processor()
    return {
        "keywords": list(processor.config.urgent_keywords),
        "count": len(processor.config.urgent_keywords),
    }


@router.post("/config/keywords/urgent")
async def add_urgent_keyword(
    request: AddItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Add an urgent keyword."""
    processor = _get_processor()
    keyword = request.value.strip().lower()

    if not keyword:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")

    if keyword in processor.config.urgent_keywords:
        return {"status": "already_exists", "keyword": keyword}

    processor.config.urgent_keywords.append(keyword)
    logger.info(f"Added urgent keyword: {keyword} (by {user.username})")

    return {
        "status": "added",
        "keyword": keyword,
        "total": len(processor.config.urgent_keywords),
    }


@router.delete("/config/keywords/urgent")
async def remove_urgent_keyword(
    request: RemoveItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Remove an urgent keyword."""
    processor = _get_processor()
    keyword = request.value.strip().lower()

    if keyword not in processor.config.urgent_keywords:
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")

    processor.config.urgent_keywords.remove(keyword)
    logger.info(f"Removed urgent keyword: {keyword} (by {user.username})")

    return {
        "status": "removed",
        "keyword": keyword,
        "total": len(processor.config.urgent_keywords),
    }


@router.get("/config/keywords/action")
async def list_action_keywords(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List action keywords."""
    processor = _get_processor()
    return {
        "keywords": list(processor.config.action_keywords),
        "count": len(processor.config.action_keywords),
    }


@router.post("/config/keywords/action")
async def add_action_keyword(
    request: AddItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Add an action keyword."""
    processor = _get_processor()
    keyword = request.value.strip().lower()

    if not keyword:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")

    if keyword in processor.config.action_keywords:
        return {"status": "already_exists", "keyword": keyword}

    processor.config.action_keywords.append(keyword)
    logger.info(f"Added action keyword: {keyword} (by {user.username})")

    return {
        "status": "added",
        "keyword": keyword,
        "total": len(processor.config.action_keywords),
    }


@router.delete("/config/keywords/action")
async def remove_action_keyword(
    request: RemoveItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Remove an action keyword."""
    processor = _get_processor()
    keyword = request.value.strip().lower()

    if keyword not in processor.config.action_keywords:
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")

    processor.config.action_keywords.remove(keyword)
    logger.info(f"Removed action keyword: {keyword} (by {user.username})")

    return {
        "status": "removed",
        "keyword": keyword,
        "total": len(processor.config.action_keywords),
    }


# =============================================================================
# App Rules Management
# =============================================================================


@router.get("/config/apps")
async def list_app_rules(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List all app priority rules."""
    processor = _get_processor()
    return {
        "priority": list(processor.config.priority_apps),
        "low_priority": list(processor.config.low_priority_apps),
        "counts": {
            "priority": len(processor.config.priority_apps),
            "low_priority": len(processor.config.low_priority_apps),
        },
    }


@router.post("/config/apps")
async def set_app_rule(
    request: AppRuleRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """
    Set an app's priority rule.

    Priority levels:
    - 'high': Add to priority_apps (higher scoring)
    - 'normal': Remove from both lists (default behavior)
    - 'low': Add to low_priority_apps (lower scoring, rarely pushed)
    """
    processor = _get_processor()
    app_name = request.app_name.strip()
    priority = request.priority.lower()

    if not app_name:
        raise HTTPException(status_code=400, detail="App name cannot be empty")

    if priority not in ("high", "normal", "low"):
        raise HTTPException(
            status_code=400,
            detail="Priority must be 'high', 'normal', or 'low'",
        )

    # Remove from both lists first
    if app_name in processor.config.priority_apps:
        processor.config.priority_apps.remove(app_name)
    if app_name in processor.config.low_priority_apps:
        processor.config.low_priority_apps.remove(app_name)

    # Add to appropriate list
    if priority == "high":
        processor.config.priority_apps.append(app_name)
    elif priority == "low":
        processor.config.low_priority_apps.append(app_name)
    # 'normal' = not in either list

    logger.info(f"Set app rule: {app_name} -> {priority} (by {user.username})")

    return {
        "status": "updated",
        "app": app_name,
        "priority": priority,
    }


@router.delete("/config/apps")
async def remove_app_rule(
    request: RemoveItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Remove an app from all priority lists (reset to normal)."""
    processor = _get_processor()
    app_name = request.value.strip()

    removed_from = []
    if app_name in processor.config.priority_apps:
        processor.config.priority_apps.remove(app_name)
        removed_from.append("priority")
    if app_name in processor.config.low_priority_apps:
        processor.config.low_priority_apps.remove(app_name)
        removed_from.append("low_priority")

    if not removed_from:
        return {"status": "not_found", "app": app_name, "message": "App had no rules"}

    logger.info(f"Removed app rule: {app_name} from {removed_from} (by {user.username})")

    return {
        "status": "removed",
        "app": app_name,
        "removed_from": removed_from,
    }


# =============================================================================
# Threshold Management
# =============================================================================


@router.get("/config/threshold")
async def get_threshold(user: User = Depends(require_auth)) -> dict[str, Any]:
    """Get the current push threshold."""
    processor = _get_processor()
    return {
        "threshold": processor.config.push_threshold,
        "description": "Notifications scoring above this value get pushed",
    }


@router.put("/config/threshold")
async def set_threshold(
    request: UpdateThresholdRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """
    Set the push threshold (0.0-1.0).

    - Lower threshold = more notifications pushed
    - Higher threshold = fewer notifications pushed
    """
    processor = _get_processor()
    old_threshold = processor.config.push_threshold
    processor.config.push_threshold = request.threshold

    logger.info(
        f"Changed push threshold: {old_threshold} -> {request.threshold} (by {user.username})"
    )

    return {
        "status": "updated",
        "old_threshold": old_threshold,
        "new_threshold": request.threshold,
    }


# =============================================================================
# User Aliases Management
# =============================================================================


@router.get("/config/aliases")
async def list_aliases(user: User = Depends(require_auth)) -> dict[str, Any]:
    """List user aliases for mention detection."""
    processor = _get_processor()
    return {
        "aliases": list(processor.config.user_aliases),
        "count": len(processor.config.user_aliases),
    }


@router.post("/config/aliases")
async def add_alias(
    request: AddItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Add a user alias for mention detection."""
    processor = _get_processor()
    alias = request.value.strip()

    if not alias:
        raise HTTPException(status_code=400, detail="Alias cannot be empty")

    if alias in processor.config.user_aliases:
        return {"status": "already_exists", "alias": alias}

    processor.config.user_aliases.append(alias)
    logger.info(f"Added user alias: {alias} (by {user.username})")

    return {
        "status": "added",
        "alias": alias,
        "total": len(processor.config.user_aliases),
    }


@router.delete("/config/aliases")
async def remove_alias(
    request: RemoveItemRequest,
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Remove a user alias."""
    processor = _get_processor()
    alias = request.value.strip()

    if alias not in processor.config.user_aliases:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")

    processor.config.user_aliases.remove(alias)
    logger.info(f"Removed user alias: {alias} (by {user.username})")

    return {
        "status": "removed",
        "alias": alias,
        "total": len(processor.config.user_aliases),
    }
