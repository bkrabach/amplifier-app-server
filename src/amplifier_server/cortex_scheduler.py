"""Cortex Scheduler - Always-on background task for proactive actions."""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amplifier_server.alarm_store import AlarmStore
    from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

# Type alias for async callbacks
AsyncCallback = Callable[[Any], Coroutine[Any, Any, Any]]


class CortexScheduler:
    """Background scheduler that periodically wakes to check state and take action.

    Features:
    - Adaptive interval: shortens after action, lengthens when idle
    - Alarm system: can be woken by scheduled alarms
    - Display awareness: knows when user has active session
    - Expiration handling: automatically expires old triage items

    The scheduler operates on a "wake cycle" pattern:
    1. Sleep for current interval (or until alarm/wake event)
    2. Check pending alarms and trigger them
    3. Expire old triage items
    4. Notify about items expiring soon (if display active)
    5. Adjust interval based on activity
    6. Repeat
    """

    DEFAULT_INTERVAL = 15 * 60  # 15 minutes
    MIN_INTERVAL = 60  # 1 minute (after action)
    MAX_INTERVAL = 60 * 60  # 1 hour (when idle)
    EXPIRING_SOON_THRESHOLD = 4 * 60 * 60  # 4 hours

    def __init__(
        self,
        notification_store: "NotificationStore",
        alarm_store: "AlarmStore",
        on_alarm_triggered: AsyncCallback | None = None,
        on_items_expiring: AsyncCallback | None = None,
    ):
        """Initialize the Cortex scheduler.

        Args:
            notification_store: Store for notification/triage data
            alarm_store: Store for scheduled alarms
            on_alarm_triggered: Async callback when an alarm triggers.
                               Called with alarm dict.
            on_items_expiring: Async callback when items are expiring soon.
                              Called with list of item dicts.
        """
        self.notification_store = notification_store
        self.alarm_store = alarm_store
        self.on_alarm_triggered = on_alarm_triggered
        self.on_items_expiring = on_items_expiring

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._current_interval = self.DEFAULT_INTERVAL
        self._last_action_time: datetime | None = None
        self._active_displays: set[str] = set()  # session_ids with active displays
        self._wake_event = asyncio.Event()  # For immediate wake-up

    async def start(self) -> None:
        """Start the scheduler.

        Begins the background wake cycle loop.
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Cortex scheduler started (interval: {self._current_interval}s)")

    async def stop(self) -> None:
        """Stop the scheduler.

        Gracefully stops the background loop and cancels any pending task.
        """
        self._running = False
        self._wake_event.set()  # Wake immediately to exit
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Cortex scheduler stopped")

    def wake_now(self) -> None:
        """Trigger an immediate wake-up.

        Use this when something important happens that shouldn't wait
        for the next scheduled wake (e.g., high-priority notification).
        """
        self._wake_event.set()

    def register_display(self, session_id: str) -> None:
        """Register an active display session.

        Args:
            session_id: Unique identifier for the display session
        """
        self._active_displays.add(session_id)
        logger.debug(f"Display registered: {session_id}")

    def unregister_display(self, session_id: str) -> None:
        """Unregister a display session.

        Args:
            session_id: Unique identifier for the display session
        """
        self._active_displays.discard(session_id)
        logger.debug(f"Display unregistered: {session_id}")

    @property
    def has_active_display(self) -> bool:
        """Check if any display session is active."""
        return len(self._active_displays) > 0

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._running

    @property
    def current_interval(self) -> int:
        """Get the current wake interval in seconds."""
        return self._current_interval

    async def _run_loop(self) -> None:
        """Main scheduler loop.

        Runs continuously until stopped, executing wake cycles at
        adaptive intervals.
        """
        while self._running:
            try:
                # Wait for interval or wake event
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self._current_interval)
                    self._wake_event.clear()
                except TimeoutError:
                    pass  # Normal timeout, proceed with wake

                if not self._running:
                    break

                # Execute wake cycle
                took_action = await self._wake_cycle()

                # Adjust interval based on activity
                self._adjust_interval(took_action)

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(60)  # Back off on error

    async def _wake_cycle(self) -> bool:
        """Execute one wake cycle.

        Returns:
            True if any action was taken, False otherwise
        """
        logger.debug("Cortex wake cycle starting")
        took_action = False

        # 1. Check and trigger pending alarms
        alarms_triggered = await self._check_alarms()
        if alarms_triggered > 0:
            took_action = True

        # 2. Expire old triage items
        expired_count = await self._expire_old_items()
        if expired_count > 0:
            logger.info(f"Expired {expired_count} old triage items")

        # 3. Check for items expiring soon (notify if display active)
        if self.has_active_display:
            expiring_items = await self._get_expiring_soon()
            if expiring_items and self.on_items_expiring:
                try:
                    await self.on_items_expiring(expiring_items)
                    took_action = True
                except Exception as e:
                    logger.error(f"Error in expiring items handler: {e}")

        # 4. Get state summary for logging
        state = await self._get_state_summary()
        logger.info(
            f"Cortex wake: {state['pending_triage']} pending, "
            f"{state['pending_alarms']} alarms, "
            f"{state['active_displays']} displays"
        )

        return took_action

    async def _check_alarms(self) -> int:
        """Check and trigger pending alarms.

        Returns:
            Number of alarms triggered
        """
        now = datetime.utcnow()
        pending = await self.alarm_store.get_pending_alarms(before=now)

        for alarm in pending:
            await self.alarm_store.mark_triggered(alarm["id"])
            logger.info(f"Alarm triggered: {alarm.get('reason', 'no reason')}")

            if self.on_alarm_triggered:
                try:
                    await self.on_alarm_triggered(alarm)
                except Exception as e:
                    logger.error(f"Error in alarm handler: {e}")

        return len(pending)

    async def _expire_old_items(self) -> int:
        """Expire triage items past their expiration.

        Returns:
            Number of items expired
        """
        return await self.notification_store.expire_old_triage_items()

    async def _get_expiring_soon(self) -> list[dict[str, Any]]:
        """Get items expiring within threshold.

        Returns:
            List of notification dicts that are expiring soon
        """
        threshold = datetime.utcnow() + timedelta(seconds=self.EXPIRING_SOON_THRESHOLD)
        items = await self.notification_store.get_triage_items(status="pending", limit=100)

        expiring = []
        for item in items:
            expires_at_str = item.get("expires_at")
            if expires_at_str:
                try:
                    expires = datetime.fromisoformat(expires_at_str)
                    if expires <= threshold:
                        expiring.append(item)
                except (ValueError, TypeError):
                    pass

        return expiring

    async def _get_state_summary(self) -> dict[str, Any]:
        """Get summary of current state.

        Returns:
            Dict with state information for logging/monitoring
        """
        pending_items = await self.notification_store.get_triage_items(status="pending", limit=1)
        pending_alarms = await self.alarm_store.get_pending_alarms()

        return {
            "pending_triage": len(pending_items),
            "pending_alarms": len(pending_alarms),
            "active_displays": len(self._active_displays),
            "current_interval": self._current_interval,
        }

    def _adjust_interval(self, took_action: bool) -> None:
        """Adjust wake interval based on activity.

        Args:
            took_action: Whether any action was taken in the last wake cycle
        """
        if took_action:
            # Shorten interval after action
            self._current_interval = max(self.MIN_INTERVAL, self._current_interval // 2)
            self._last_action_time = datetime.utcnow()
        else:
            # Gradually lengthen when idle
            time_since_action = (
                (datetime.utcnow() - self._last_action_time).total_seconds()
                if self._last_action_time
                else float("inf")
            )

            if time_since_action > 30 * 60:  # 30 min since last action
                self._current_interval = min(self.MAX_INTERVAL, int(self._current_interval * 1.5))

        logger.debug(f"Next wake in {self._current_interval}s")

    # =========================================================================
    # Public API for Cortex to Set Alarms
    # =========================================================================

    async def set_alarm(
        self,
        trigger_at: datetime | str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> int:
        """Set an alarm for future wake-up.

        This is the primary interface for Cortex Core to schedule
        proactive actions at specific times.

        Args:
            trigger_at: When the alarm should trigger (datetime or ISO string)
            reason: Human-readable reason for the alarm
            context: Optional context data to pass to the alarm handler

        Returns:
            The ID of the created alarm
        """
        alarm_id = await self.alarm_store.create_alarm(
            trigger_at=trigger_at,
            reason=reason,
            source="cortex",
            context=context,
        )
        logger.info(f"Alarm {alarm_id} set for {trigger_at}: {reason}")
        return alarm_id

    async def cancel_alarm(self, alarm_id: int) -> None:
        """Cancel a previously set alarm.

        Args:
            alarm_id: ID of the alarm to cancel
        """
        await self.alarm_store.cancel_alarm(alarm_id)
        logger.info(f"Alarm {alarm_id} cancelled")

    async def get_next_alarm(self) -> dict[str, Any] | None:
        """Get the next pending alarm.

        Returns:
            Alarm dict or None if no pending alarms
        """
        return await self.alarm_store.get_next_alarm()

    async def get_status(self) -> dict[str, Any]:
        """Get scheduler status information.

        Returns:
            Dict with scheduler status for monitoring/debugging
        """
        next_alarm = await self.alarm_store.get_next_alarm()
        state = await self._get_state_summary()

        return {
            "running": self._running,
            "current_interval_seconds": self._current_interval,
            "last_action_time": (
                self._last_action_time.isoformat() if self._last_action_time else None
            ),
            "active_displays": list(self._active_displays),
            "pending_triage_count": state["pending_triage"],
            "pending_alarms_count": state["pending_alarms"],
            "next_alarm": (
                {
                    "id": next_alarm["id"],
                    "trigger_at": next_alarm["trigger_at"],
                    "reason": next_alarm.get("reason"),
                }
                if next_alarm
                else None
            ),
        }
