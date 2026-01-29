"""Triage API endpoints for managing notification follow-through."""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from amplifier_server.auth import User, require_auth
from amplifier_server.feedback_store import FeedbackStore
from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triage", tags=["triage"])


# =============================================================================
# Pydantic Models
# =============================================================================


class TriageItem(BaseModel):
    """A notification in the triage queue."""

    id: int
    app_name: str | None = None
    title: str | None = None
    body: str | None = None
    sender: str | None = None
    triage_status: str | None = None
    expires_at: str | None = None
    surfaced_at: str | None = None
    suggested_response: dict[str, Any] | None = None
    quick_reaction: str | None = None
    relevance_score: float | None = None
    decision: str | None = None
    rationale: str | None = None
    created_at: str | None = None
    device_id: str | None = None


class TriageActionRequest(BaseModel):
    """Request to take action on a triage item."""

    action: str = Field(..., description="Action: 'dealt_with', 'dismissed', 'already_handled'")
    quick_reaction: str | None = Field(None, description="Optional emoji: 👍👎⏰❓")
    feedback_type: str | None = Field(
        None, description="Optional: 'good_call', 'bad_call', 'wrong_timing'"
    )
    feedback_text: str | None = Field(None, description="Optional detailed feedback")


class BulkActionRequest(BaseModel):
    """Request to take action on multiple triage items."""

    item_ids: list[int] = Field(..., description="List of notification IDs")
    action: str = Field(..., description="Action: 'dealt_with', 'dismissed', 'already_handled'")
    quick_reaction: str | None = Field(None, description="Optional emoji: 👍👎⏰❓")
    feedback_type: str | None = Field(
        None, description="Optional: 'good_call', 'bad_call', 'wrong_timing'"
    )
    feedback_text: str | None = Field(None, description="Optional detailed feedback")


class TriageListResponse(BaseModel):
    """Response with triage items grouped by status."""

    surfaced: list[TriageItem] = []  # Punched through, awaiting confirmation
    expiring_soon: list[TriageItem] = []  # Expiring within 4 hours
    pending: list[TriageItem] = []  # Normal pending items
    expired: list[TriageItem] = []  # Expired items (for review)
    total_count: int = 0


class TriageStatsResponse(BaseModel):
    """Response with triage statistics."""

    pending_count: int = 0
    surfaced_count: int = 0
    handled_today: int = 0
    dismissed_today: int = 0
    expired_today: int = 0
    feedback_stats: dict[str, Any] = {}


# =============================================================================
# Module-level Storage for Injected Dependencies
# =============================================================================

_notification_store: NotificationStore | None = None
_feedback_store: FeedbackStore | None = None

# Threshold for "expiring soon" (4 hours)
EXPIRING_SOON_THRESHOLD_HOURS = 4


def inject_stores(
    notification_store: NotificationStore,
    feedback_store: FeedbackStore,
) -> None:
    """Inject store references from server startup."""
    global _notification_store, _feedback_store
    _notification_store = notification_store
    _feedback_store = feedback_store


def get_notification_store() -> NotificationStore:
    """Dependency to get notification store - injected by server."""
    if _notification_store is None:
        raise NotImplementedError("Notification store not injected")
    return _notification_store


def get_feedback_store() -> FeedbackStore:
    """Dependency to get feedback store - injected by server."""
    if _feedback_store is None:
        raise NotImplementedError("Feedback store not injected")
    return _feedback_store


# =============================================================================
# Helper Functions
# =============================================================================


def _notification_to_triage_item(notification: dict[str, Any]) -> TriageItem:
    """Convert a notification dict to a TriageItem model."""
    return TriageItem(
        id=notification["id"],
        app_name=notification.get("app_name"),
        title=notification.get("title"),
        body=notification.get("body"),
        sender=notification.get("sender"),
        triage_status=notification.get("triage_status"),
        expires_at=notification.get("expires_at"),
        surfaced_at=notification.get("surfaced_at"),
        suggested_response=notification.get("suggested_response"),
        quick_reaction=notification.get("quick_reaction"),
        relevance_score=notification.get("relevance_score"),
        decision=notification.get("decision"),
        rationale=notification.get("rationale"),
        created_at=notification.get("ingested_at"),
        device_id=notification.get("device_id"),
    )


def _is_expiring_soon(item: dict[str, Any]) -> bool:
    """Check if an item is expiring within the threshold."""
    expires_at = item.get("expires_at")
    if not expires_at:
        return False

    try:
        expires_dt = datetime.fromisoformat(expires_at)
        threshold = datetime.utcnow() + timedelta(hours=EXPIRING_SOON_THRESHOLD_HOURS)
        return expires_dt <= threshold
    except (ValueError, TypeError):
        return False


def _map_action_to_status(action: str) -> str:
    """Map user action to triage status."""
    action_map = {
        "dealt_with": "handled",
        "dismissed": "dismissed",
        "already_handled": "handled",
    }
    if action not in action_map:
        raise ValueError(f"Invalid action: {action}. Must be one of: {list(action_map.keys())}")
    return action_map[action]


# =============================================================================
# Endpoints
# =============================================================================


def _is_expired(item: dict[str, Any]) -> bool:
    """Check if an item's expiration time has passed."""
    expires_at = item.get("expires_at")
    if not expires_at:
        return False

    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        # Make naive for comparison if needed
        if expires_dt.tzinfo:
            expires_dt = expires_dt.replace(tzinfo=None)
        return expires_dt <= datetime.utcnow()
    except (ValueError, TypeError):
        return False


@router.get("/items", response_model=TriageListResponse)
async def get_triage_items(
    user: User = Depends(require_auth),
    limit: int = Query(default=100, le=500),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> TriageListResponse:
    """Get all triage items, grouped by status.

    Items are grouped into:
    - surfaced: Items that were pushed/surfaced and await user confirmation
    - expiring_soon: Pending items expiring within 4 hours
    - pending: Normal pending items not expiring soon
    - expired: Items that have expired (for review) - based on expires_at time
    
    Note: Items are categorized by their actual expiration time, not just status.
    Items with passed expires_at are automatically shown in expired section.
    """
    # Get surfaced items
    surfaced_raw = await notification_store.get_triage_items(status="surfaced", limit=limit)
    surfaced = []
    auto_expired = []  # Surfaced items that have expired
    
    for item in surfaced_raw:
        if _is_expired(item):
            auto_expired.append(_notification_to_triage_item(item))
            # Update status in background (don't block)
            await notification_store.update_triage_status(item["id"], "expired")
        else:
            surfaced.append(_notification_to_triage_item(item))

    # Get pending items
    pending_raw = await notification_store.get_triage_items(status="pending", limit=limit)

    # Split pending into expiring_soon, regular pending, and auto-expired
    expiring_soon = []
    pending = []

    for item in pending_raw:
        if _is_expired(item):
            auto_expired.append(_notification_to_triage_item(item))
            # Update status in background
            await notification_store.update_triage_status(item["id"], "expired")
        elif _is_expiring_soon(item):
            expiring_soon.append(_notification_to_triage_item(item))
        else:
            pending.append(_notification_to_triage_item(item))

    # Get already-expired items (status = expired) and combine with auto-expired
    expired_raw = await notification_store.get_triage_items(status="expired", limit=100)
    expired = auto_expired + [_notification_to_triage_item(n) for n in expired_raw]
    
    # Sort expired by created_at descending (most recent first), limit to 50 for review
    expired.sort(key=lambda x: x.created_at or "", reverse=True)
    expired = expired[:50]

    # Total count excludes expired items (they're for review only)
    total_count = len(surfaced) + len(expiring_soon) + len(pending)

    return TriageListResponse(
        surfaced=surfaced,
        expiring_soon=expiring_soon,
        pending=pending,
        expired=expired,
        total_count=total_count,
    )


@router.get("/items/{item_id}", response_model=TriageItem)
async def get_triage_item(
    item_id: int,
    user: User = Depends(require_auth),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> TriageItem:
    """Get a specific triage item by ID."""
    notification = await notification_store.get_by_id(item_id)

    if not notification:
        raise HTTPException(status_code=404, detail="Triage item not found")

    # Verify it's a triage item (has triage_status)
    if not notification.get("triage_status"):
        raise HTTPException(status_code=404, detail="Item is not in triage queue")

    return _notification_to_triage_item(notification)


@router.post("/items/{item_id}/action")
async def take_action(
    item_id: int,
    request: TriageActionRequest,
    user: User = Depends(require_auth),
    notification_store: NotificationStore = Depends(get_notification_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
) -> dict[str, Any]:
    """Take action on a triage item (deal with, dismiss, or mark handled).

    Actions:
    - dealt_with: User dealt with the notification
    - dismissed: User dismissed without action
    - already_handled: Notification was already handled elsewhere

    Optional feedback:
    - quick_reaction: Emoji reaction (👍👎⏰❓)
    - feedback_type: 'good_call', 'bad_call', 'wrong_timing'
    - feedback_text: Detailed explanation
    """
    # Get the notification to record original score/decision
    notification = await notification_store.get_by_id(item_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Triage item not found")

    if not notification.get("triage_status"):
        raise HTTPException(status_code=400, detail="Item is not in triage queue")

    # Map action to status
    try:
        new_status = _map_action_to_status(request.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Calculate time in queue
    time_in_queue = None
    if notification.get("surfaced_at"):
        try:
            surfaced_dt = datetime.fromisoformat(notification["surfaced_at"])
            time_in_queue = int((datetime.utcnow() - surfaced_dt).total_seconds())
        except (ValueError, TypeError):
            pass

    # Update triage status
    await notification_store.update_triage_status(
        notification_id=item_id,
        status=new_status,
        quick_reaction=request.quick_reaction,
    )

    # Record feedback
    await feedback_store.record_feedback(
        notification_id=item_id,
        action=request.action,
        feedback_type=request.feedback_type,
        feedback_text=request.feedback_text,
        original_score=notification.get("relevance_score"),
        original_decision=notification.get("decision"),
        time_in_queue_seconds=time_in_queue,
    )

    logger.info(
        f"Triage action: {request.action} on item {item_id} "
        f"(original: {notification.get('decision')}, score: {notification.get('relevance_score')})"
    )

    return {
        "status": "success",
        "item_id": item_id,
        "action": request.action,
        "new_status": new_status,
        "feedback_recorded": request.feedback_type is not None,
    }


@router.post("/items/bulk-action")
async def bulk_action(
    request: BulkActionRequest,
    user: User = Depends(require_auth),
    notification_store: NotificationStore = Depends(get_notification_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
) -> dict[str, Any]:
    """Take action on multiple items at once.

    Applies the same action to all specified items.
    Returns summary of successes and failures.
    """
    if not request.item_ids:
        raise HTTPException(status_code=400, detail="No item IDs provided")

    if len(request.item_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 items per bulk action")

    # Map action to status
    try:
        new_status = _map_action_to_status(request.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    successes = []
    failures = []

    for item_id in request.item_ids:
        try:
            # Get the notification
            notification = await notification_store.get_by_id(item_id)
            if not notification:
                failures.append({"id": item_id, "error": "Not found"})
                continue

            if not notification.get("triage_status"):
                failures.append({"id": item_id, "error": "Not in triage queue"})
                continue

            # Calculate time in queue
            time_in_queue = None
            if notification.get("surfaced_at"):
                try:
                    surfaced_dt = datetime.fromisoformat(notification["surfaced_at"])
                    time_in_queue = int((datetime.utcnow() - surfaced_dt).total_seconds())
                except (ValueError, TypeError):
                    pass

            # Update status
            await notification_store.update_triage_status(
                notification_id=item_id,
                status=new_status,
                quick_reaction=request.quick_reaction,
            )

            # Record feedback
            await feedback_store.record_feedback(
                notification_id=item_id,
                action=request.action,
                feedback_type=request.feedback_type,
                feedback_text=request.feedback_text,
                original_score=notification.get("relevance_score"),
                original_decision=notification.get("decision"),
                time_in_queue_seconds=time_in_queue,
            )

            successes.append(item_id)

        except Exception as e:
            logger.error(f"Error processing bulk action for item {item_id}: {e}")
            failures.append({"id": item_id, "error": str(e)})

    logger.info(
        f"Bulk triage action: {request.action} on {len(request.item_ids)} items "
        f"({len(successes)} success, {len(failures)} failed)"
    )

    return {
        "status": "completed",
        "action": request.action,
        "total_requested": len(request.item_ids),
        "successful": len(successes),
        "failed": len(failures),
        "success_ids": successes,
        "failures": failures,
    }


@router.get("/stats", response_model=TriageStatsResponse)
async def get_triage_stats(
    user: User = Depends(require_auth),
    notification_store: NotificationStore = Depends(get_notification_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
) -> TriageStatsResponse:
    """Get triage statistics and feedback insights.

    Returns counts by status and feedback statistics.
    """
    # Get pending and surfaced counts
    pending_items = await notification_store.get_triage_items(status="pending", limit=1000)
    surfaced_items = await notification_store.get_triage_items(status="surfaced", limit=1000)

    # Get feedback stats
    feedback_stats = await feedback_store.get_feedback_stats()

    # For today's counts, we'd need to add date filtering to stores
    # For now, approximate from feedback stats
    today_actions = feedback_stats.get("by_action", {})
    handled_today = today_actions.get("dealt_with", 0) + today_actions.get("already_handled", 0)
    dismissed_today = today_actions.get("dismissed", 0)

    return TriageStatsResponse(
        pending_count=len(pending_items),
        surfaced_count=len(surfaced_items),
        handled_today=handled_today,
        dismissed_today=dismissed_today,
        expired_today=0,  # Would need date filtering in store
        feedback_stats=feedback_stats,
    )


@router.post("/reprocess-expiration")
async def reprocess_expiration(
    user: User = Depends(require_auth),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Re-calculate expiration for all pending triage items.

    Useful after improving expiration logic to apply to existing items.
    Uses smarter time-sensitive pattern detection to set appropriate
    expiration times.
    """
    import re

    # Get all pending items
    items = await notification_store.get_triage_items(status="pending", limit=1000)

    updated = 0
    expired = 0

    for item in items:
        # Re-calculate expiration based on content
        content = f"{item.get('title', '')} {item.get('body', '')}".lower()

        now = datetime.utcnow()
        end_of_today = now.replace(hour=23, minute=59, second=59)
        new_expires = None

        # Apply same logic as processor
        if re.search(r"\b(tonight|this evening|this afternoon|this morning|today)\b", content):
            new_expires = end_of_today
        elif re.search(r"\btomorrow\b", content):
            new_expires = end_of_today + timedelta(days=1)
        elif re.search(r"\b(spend(ing)? the night|sleep\s*over|staying over)\b", content):
            new_expires = end_of_today

        if new_expires:
            # Check if this should already be expired
            if new_expires < now:
                # Mark as expired
                await notification_store.update_triage_status(item["id"], "expired")
                expired += 1
            else:
                # Update expiration time
                await notification_store.update_expiration(item["id"], new_expires.isoformat())
                updated += 1

    logger.info(
        f"Reprocessed expiration: {len(items)} checked, {updated} updated, {expired} expired"
    )

    return {
        "success": True,
        "items_checked": len(items),
        "items_updated": updated,
        "items_expired": expired,
    }
