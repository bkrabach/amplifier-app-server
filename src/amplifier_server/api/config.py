"""Configuration API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

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


@router.get("/config")
async def get_config(user: User = Depends(require_auth)) -> dict[str, Any]:
    """
    Get current notification processing configuration.

    Returns VIP senders, keywords, thresholds, and other settings
    that control how notifications are scored and routed.
    """
    if not _notification_processor:
        raise HTTPException(status_code=503, detail="Configuration not available")

    config = _notification_processor.config

    return {
        "llm_enabled": _notification_processor.use_llm,
        "vip_senders": list(config.vip_senders),
        "keywords": list(config.urgent_keywords),
        "push_threshold": config.push_threshold,
        "focus_hours": [],  # TODO: Add focus hours to config
    }
