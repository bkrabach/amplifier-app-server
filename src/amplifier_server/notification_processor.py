"""Notification processing and scoring."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from amplifier_server.device_manager import DeviceManager
from amplifier_server.models import PushNotificationRequest
from amplifier_server.notification_store import NotificationStore

if TYPE_CHECKING:
    from amplifier_server.llm_scorer import LLMScorer

logger = logging.getLogger(__name__)


@dataclass
class ScoringConfig:
    """Configuration for notification scoring."""

    # VIP senders - always high priority
    vip_senders: list[str] = field(default_factory=list)

    # Keywords that indicate urgency
    urgent_keywords: list[str] = field(
        default_factory=lambda: [
            "urgent",
            "asap",
            "immediately",
            "critical",
            "emergency",
            "deadline",
            "today",
            "now",
            "important",
            "action required",
            "blocking",
            "blocked",
            "p0",
            "p1",
            "outage",
            "down",
        ]
    )

    # Keywords that indicate decisions/action needed
    action_keywords: list[str] = field(
        default_factory=lambda: [
            "approve",
            "review",
            "sign",
            "decision",
            "confirm",
            "reply",
            "respond",
            "answer",
            "vote",
            "choose",
        ]
    )

    # Apps to prioritize
    priority_apps: list[str] = field(
        default_factory=lambda: [
            "Microsoft Teams",
            "Outlook",
            "Microsoft Outlook",
        ]
    )

    # Apps to deprioritize (still store, but don't alert)
    low_priority_apps: list[str] = field(
        default_factory=lambda: [
            "Snipping Tool",
            "Phone Link",
            "Windows Security",
            "Microsoft Store",
            "Settings",
        ]
    )

    # Threshold for pushing notification (0-1)
    push_threshold: float = 0.6

    # User's name/aliases for mention detection
    user_aliases: list[str] = field(default_factory=list)


@dataclass
class ScoringResult:
    """Result of scoring a notification."""

    score: float  # 0.0 to 1.0
    decision: str  # "push", "summarize", "suppress"
    rationale: str
    tags: list[str] = field(default_factory=list)


class NotificationProcessor:
    """Processes and scores incoming notifications.

    Decides which notifications warrant immediate attention vs. summarization.
    Supports both heuristic (fast) and LLM-based (smart) scoring.
    """

    def __init__(
        self,
        notification_store: NotificationStore,
        device_manager: DeviceManager,
        config: ScoringConfig | None = None,
        llm_scorer: "LLMScorer | None" = None,
        use_llm: bool = False,
    ):
        self.store = notification_store
        self.device_manager = device_manager
        self.config = config or ScoringConfig()
        self.llm_scorer = llm_scorer
        self.use_llm = use_llm  # Whether to use LLM scoring (vs heuristics only)

        # Processing queue
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background processor."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("Notification processor started")

    async def stop(self) -> None:
        """Stop the background processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Notification processor stopped")

    async def enqueue(self, notification_id: int) -> None:
        """Add a notification to the processing queue."""
        await self._queue.put(notification_id)

    async def _process_loop(self) -> None:
        """Background loop that processes queued notifications."""
        while self._running:
            try:
                # Wait for notification with timeout
                try:
                    notification_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                # Process the notification
                await self._process_notification(notification_id)

            except Exception as e:
                logger.error(f"Error in processor loop: {e}", exc_info=True)

    async def _process_notification(self, notification_id: int) -> None:
        """Process a single notification."""
        # Get notification from store
        notification = await self.store.get_by_id(notification_id)
        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return

        # Score the notification (LLM or heuristics)
        if self.use_llm and self.llm_scorer:
            result = await self._score_with_llm(notification)
        else:
            result = self._score_notification(notification)

        # Update store with results
        await self.store.mark_processed(
            notification_id=notification_id,
            relevance_score=result.score,
            decision=result.decision,
            rationale=result.rationale,
        )

        logger.info(
            f"Processed notification {notification_id}: "
            f"score={result.score:.2f}, decision={result.decision}"
        )

        # Create triage entry for non-suppressed items
        if result.decision in ("push", "summarize"):
            # Calculate expiration (7 days default, shorter for time-sensitive)
            expires_at = self._calculate_expiration(notification, result)

            # Generate suggested response (eager generation)
            suggested_response = None
            if self.use_llm and self.llm_scorer:
                suggested_response = await self._generate_suggestions(notification, result)

            # Create triage item
            # For 'push' items, mark as 'surfaced' since user saw it
            triage_status = "surfaced" if result.decision == "push" else "pending"
            await self.store.create_triage_item(
                notification_id=notification_id,
                expires_at=expires_at,
                suggested_response=suggested_response,
                initial_status=triage_status,
            )

        # If high priority, push to device
        if result.decision == "push":
            await self._push_notification(notification, result)

    def _calculate_expiration(self, notification: dict[str, Any], result: ScoringResult) -> str:
        """Calculate expiration time based on notification content.

        Time-sensitive patterns:
        - "tonight", "this evening" → end of today
        - "today", "this morning", "this afternoon" → end of today
        - "tomorrow" → end of tomorrow
        - "this week", "this weekend" → end of week
        - Calendar/meeting notifications → 4 hours after assumed time
        - Deadline keywords → 24 hours
        - Default → 7 days

        Args:
            notification: The notification dict
            result: The scoring result (unused but available for future logic)

        Returns:
            ISO format timestamp string for expiration
        """
        import re

        _ = result  # Available for future enhancements

        now = datetime.utcnow()
        content = f"{notification.get('title', '')} {notification.get('body', '')}".lower()
        app_name = (notification.get("app_name") or "").lower()

        # End of today (11:59 PM)
        end_of_today = now.replace(hour=23, minute=59, second=59)

        # Tonight / this evening / today patterns - expire at end of today
        if re.search(r"\b(tonight|this evening|this afternoon|this morning|today)\b", content):
            return end_of_today.isoformat()

        # Tomorrow - expire at end of tomorrow
        if re.search(r"\btomorrow\b", content):
            return (end_of_today + timedelta(days=1)).isoformat()

        # This week / this weekend
        if re.search(r"\b(this week|this weekend)\b", content):
            # End of this week (Sunday)
            days_until_sunday = 6 - now.weekday()
            if days_until_sunday < 0:
                days_until_sunday = 0
            return (end_of_today + timedelta(days=days_until_sunday)).isoformat()

        # Spending the night / sleepover patterns (usually same-day relevance)
        if re.search(r"\b(spend(ing)? the night|sleep\s*over|staying over)\b", content):
            return end_of_today.isoformat()

        # Calendar/meeting notifications - expire in 4 hours
        if "calendar" in app_name or re.search(r"\b(meeting|call|appointment)\b", content):
            return (now + timedelta(hours=4)).isoformat()

        # Deadline keywords - 24 hours
        if re.search(r"\b(deadline|urgent|asap|eod|end of day|by today|due today)\b", content):
            return (now + timedelta(hours=24)).isoformat()

        # Default: 7 days
        return (now + timedelta(days=7)).isoformat()

    async def _generate_suggestions(
        self, notification: dict[str, Any], result: ScoringResult
    ) -> dict[str, Any] | None:
        """Generate suggested responses for the notification.

        Args:
            notification: The notification dict
            result: The scoring result (unused but available for future logic)

        Returns:
            dict with:
            - quick_replies: List of short responses
            - detailed_response: Longer drafted response if appropriate
            - actions: Suggested actions (e.g., "Open Teams", "Schedule follow-up")

            Returns None if generation fails or LLM is not available.
        """
        _ = result  # Available for future enhancements

        try:
            if not self.llm_scorer:
                return None

            # Use LLM to generate suggestions
            suggestions = await self.llm_scorer.generate_suggestions(notification)
            return suggestions
        except Exception as e:
            logger.warning(f"Failed to generate suggestions: {e}")
            return None

    async def _score_with_llm(self, notification: dict[str, Any]) -> ScoringResult:
        """Score notification using LLM.

        Falls back to heuristics if LLM fails.
        """
        try:
            # Score using LLM
            if self.llm_scorer:
                llm_result = await self.llm_scorer.score(notification)

                return ScoringResult(
                    score=llm_result.score,
                    decision=llm_result.decision,
                    rationale=f"[LLM] {llm_result.rationale}",
                    tags=llm_result.tags,
                )
        except Exception as e:
            logger.warning(f"LLM scoring failed, falling back to heuristics: {e}")

        # Fallback to heuristics
        return self._score_notification(notification)

    def _score_notification(self, notification: dict[str, Any]) -> ScoringResult:
        """Score a notification based on rules.

        Returns a score from 0.0 (ignore) to 1.0 (critical).
        """
        score = 0.0
        tags = []
        reasons = []

        app_name = notification.get("app_name") or notification.get("app_id", "")
        title = notification.get("title", "")
        body = notification.get("body", "") or ""
        sender = notification.get("sender", "") or ""
        content = f"{title} {body}".lower()

        # Check for low-priority apps first
        for low_app in self.config.low_priority_apps:
            if low_app.lower() in app_name.lower():
                return ScoringResult(
                    score=0.1,
                    decision="suppress",
                    rationale=f"Low-priority app: {app_name}",
                    tags=["low-priority-app"],
                )

        # VIP sender check
        for vip in self.config.vip_senders:
            if vip.lower() in sender.lower():
                score += 0.5
                tags.append("vip")
                reasons.append(f"VIP sender: {sender}")
                break

        # Priority app boost
        for priority_app in self.config.priority_apps:
            if priority_app.lower() in app_name.lower():
                score += 0.2
                tags.append("priority-app")
                reasons.append(f"Priority app: {app_name}")
                break

        # User mention check
        for alias in self.config.user_aliases:
            if alias.lower() in content:
                score += 0.3
                tags.append("mention")
                reasons.append(f"Mentioned: {alias}")
                break

        # Urgent keyword check
        for keyword in self.config.urgent_keywords:
            if keyword.lower() in content:
                score += 0.3
                tags.append("urgent")
                reasons.append(f"Urgent keyword: {keyword}")
                break

        # Action keyword check
        for keyword in self.config.action_keywords:
            if keyword.lower() in content:
                score += 0.2
                tags.append("action-needed")
                reasons.append(f"Action keyword: {keyword}")
                break

        # Cap score at 1.0
        score = min(score, 1.0)

        # Determine decision based on score
        if score >= self.config.push_threshold:
            decision = "push"
        elif score >= 0.3:
            decision = "summarize"
        else:
            decision = "suppress"

        rationale = "; ".join(reasons) if reasons else "No special signals detected"

        return ScoringResult(
            score=score,
            decision=decision,
            rationale=rationale,
            tags=tags,
        )

    async def _push_notification(
        self,
        notification: dict[str, Any],
        result: ScoringResult,
    ) -> None:
        """Push a high-priority notification to the user's device."""
        device_id = notification.get("device_id")

        # Create push notification
        push_request = PushNotificationRequest(
            device_id=device_id,
            title=f"🔔 {notification.get('title', 'Notification')}",
            body=notification.get("body", ""),
            urgency="high" if result.score >= 0.8 else "normal",
            rationale=result.rationale,
            app_source=notification.get("app_name") or notification.get("app_id"),
        )

        # Send via device manager
        results = await self.device_manager.push_notification(push_request)

        sent = sum(1 for s in results.values() if s)
        logger.info(
            f"Pushed notification to {sent} device(s): {notification.get('title', '')[:50]}"
        )

    def update_config(self, **kwargs) -> None:
        """Update scoring configuration."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Updated config: {key}")

    def add_vip(self, sender: str) -> None:
        """Add a VIP sender."""
        if sender not in self.config.vip_senders:
            self.config.vip_senders.append(sender)
            logger.info(f"Added VIP: {sender}")

    def remove_vip(self, sender: str) -> None:
        """Remove a VIP sender."""
        if sender in self.config.vip_senders:
            self.config.vip_senders.remove(sender)
            logger.info(f"Removed VIP: {sender}")

    def add_keyword(self, keyword: str, category: str = "urgent") -> None:
        """Add a keyword to watch for."""
        target = (
            self.config.urgent_keywords if category == "urgent" else self.config.action_keywords
        )
        if keyword not in target:
            target.append(keyword)
            logger.info(f"Added {category} keyword: {keyword}")

    def set_llm_scorer(self, scorer: "LLMScorer") -> None:
        """Set the LLM scorer instance."""
        self.llm_scorer = scorer
        logger.info("LLM scorer configured")

    def enable_llm_scoring(self, enabled: bool = True) -> None:
        """Enable or disable LLM-based scoring."""
        self.use_llm = enabled
        mode = "LLM" if enabled else "heuristics"
        logger.info(f"Scoring mode: {mode}")
