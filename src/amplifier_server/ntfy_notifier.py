"""ntfy.sh push notification integration.

Sends notifications to ntfy.sh for delivery to Android/iOS devices.
The ntfy app on the phone receives these and displays them as native
OS notifications, which can also reach smartwatches.

Setup:
1. Install ntfy app on your phone: https://ntfy.sh/
2. Subscribe to your topic (e.g., cortex-yourname-randomstring)
3. Set NTFY_TOPIC in .env or config

Usage:
    notifier = NtfyNotifier(topic="cortex-bkrabach-abc123")
    await notifier.send(
        title="New message from Alice",
        message="Can you review the PR?",
        priority="high",
        tags=["incoming_envelope", "Teams"],
    )
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ntfy.sh priority levels
PRIORITY_URGENT = 5  # Max priority, bypasses DND
PRIORITY_HIGH = 4
PRIORITY_DEFAULT = 3
PRIORITY_LOW = 2
PRIORITY_MIN = 1


@dataclass
class NtfyConfig:
    """Configuration for ntfy notifications."""

    # The topic to publish to (required)
    # Should be unique and hard to guess, e.g., cortex-username-randomstring
    topic: str

    # ntfy server URL (default is public ntfy.sh, can self-host)
    server: str = "https://ntfy.sh"

    # Default priority for notifications
    default_priority: int = PRIORITY_HIGH

    # Whether to include click action to open Cortex web UI
    include_click_action: bool = True

    # Base URL for Cortex web UI (for click actions)
    cortex_web_url: str | None = None

    # Whether ntfy is enabled
    enabled: bool = True


class NtfyNotifier:
    """Send push notifications via ntfy.sh."""

    def __init__(self, config: NtfyConfig | None = None, **kwargs):
        """Initialize the notifier.

        Args:
            config: NtfyConfig instance
            **kwargs: Can also pass config fields directly (topic, server, etc.)
        """
        if config:
            self.config = config
        else:
            # Allow passing config fields directly
            topic = kwargs.get("topic")
            if not topic:
                raise ValueError("ntfy topic is required")
            self.config = NtfyConfig(
                topic=topic,
                server=kwargs.get("server", "https://ntfy.sh"),
                default_priority=kwargs.get("default_priority", PRIORITY_HIGH),
                include_click_action=kwargs.get("include_click_action", True),
                cortex_web_url=kwargs.get("cortex_web_url"),
                enabled=kwargs.get("enabled", True),
            )

        self._client = httpx.AsyncClient(timeout=10.0)

    async def send(
        self,
        title: str,
        message: str,
        priority: str | int | None = None,
        tags: list[str] | None = None,
        click_url: str | None = None,
        actions: list[dict[str, str]] | None = None,
        attachment_url: str | None = None,
        notification_id: str | None = None,
    ) -> bool:
        """Send a notification via ntfy.

        Args:
            title: Notification title
            message: Notification body
            priority: Priority level ("urgent", "high", "default", "low", "min")
                     or int (1-5)
            tags: List of tags/emojis (e.g., ["warning", "robot"])
                 See https://docs.ntfy.sh/emojis/ for emoji shortcodes
            click_url: URL to open when notification is clicked
            actions: List of action buttons, each dict with:
                    {"action": "view", "label": "Open", "url": "..."}
            attachment_url: URL to an attachment (image, file)
            notification_id: Unique ID for this notification (for updates/dedup)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.config.enabled:
            logger.debug("ntfy disabled, skipping notification")
            return False

        # Build the URL
        url = f"{self.config.server.rstrip('/')}/{self.config.topic}"

        # Convert priority
        if isinstance(priority, str):
            priority_map = {
                "urgent": PRIORITY_URGENT,
                "high": PRIORITY_HIGH,
                "default": PRIORITY_DEFAULT,
                "normal": PRIORITY_DEFAULT,
                "low": PRIORITY_LOW,
                "min": PRIORITY_MIN,
            }
            priority = priority_map.get(priority.lower(), self.config.default_priority)
        elif priority is None:
            priority = self.config.default_priority

        # Build headers
        headers: dict[str, str] = {
            "Title": title,
            "Priority": str(priority),
        }

        # Add tags if provided
        if tags:
            headers["Tags"] = ",".join(tags)

        # Add click action
        if click_url:
            headers["Click"] = click_url
        elif self.config.include_click_action and self.config.cortex_web_url:
            headers["Click"] = self.config.cortex_web_url

        # Add attachment
        if attachment_url:
            headers["Attach"] = attachment_url

        # Add notification ID for deduplication
        if notification_id:
            headers["X-Message-Id"] = notification_id

        # Add action buttons
        if actions:
            # Format: action=view, Open app, https://example.com; action=http, ...
            action_strs = []
            for action in actions:
                action_type = action.get("action", "view")
                label = action.get("label", "Open")
                action_url = action.get("url", "")
                action_strs.append(f"{action_type}, {label}, {action_url}")
            headers["Actions"] = "; ".join(action_strs)

        try:
            response = await self._client.post(url, content=message, headers=headers)

            if response.status_code == 200:
                logger.info(f"ntfy: Sent notification '{title[:50]}' to topic {self.config.topic}")
                return True
            else:
                logger.warning(
                    f"ntfy: Failed to send notification: {response.status_code} {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"ntfy: Error sending notification: {e}")
            return False

    async def send_cortex_notification(
        self,
        notification: dict[str, Any],
        score: float,
        rationale: str | None = None,
        notification_id: str | None = None,
    ) -> bool:
        """Send a Cortex notification via ntfy.

        Convenience method that formats a Cortex notification appropriately.

        Args:
            notification: The notification dict from Cortex
            score: The relevance score (0-1)
            rationale: Why this notification was surfaced
            notification_id: Unique ID for deduplication

        Returns:
            True if sent successfully
        """
        # Extract fields
        title = notification.get("title", "Notification")
        body = notification.get("body", "")
        app_name = notification.get("app_name") or notification.get("app_id", "Unknown")

        # Determine priority based on score
        if score >= 0.9:
            priority = PRIORITY_URGENT
        elif score >= 0.7:
            priority = PRIORITY_HIGH
        else:
            priority = PRIORITY_DEFAULT

        # Build tags based on app
        tags = self._get_tags_for_app(app_name)

        # Add score indicator
        if score >= 0.9:
            tags.insert(0, "rotating_light")  # 🚨
        elif score >= 0.7:
            tags.insert(0, "bell")  # 🔔

        # Build message with rationale if available
        message = body
        if rationale:
            message = f"{body}\n\n📊 {rationale}"

        # Format title with app source
        full_title = f"{app_name}: {title}"

        return await self.send(
            title=full_title,
            message=message,
            priority=priority,
            tags=tags,
            notification_id=notification_id,
        )

    def _get_tags_for_app(self, app_name: str) -> list[str]:
        """Get emoji tags based on the source app."""
        app_lower = app_name.lower()

        if "teams" in app_lower:
            return ["speech_balloon", "microsoft"]
        elif "outlook" in app_lower or "mail" in app_lower:
            return ["incoming_envelope"]
        elif "whatsapp" in app_lower:
            return ["green_circle", "speech_balloon"]
        elif "slack" in app_lower:
            return ["hash", "speech_balloon"]
        elif "calendar" in app_lower:
            return ["calendar"]
        elif "signal" in app_lower:
            return ["blue_circle", "lock"]
        elif "discord" in app_lower:
            return ["video_game", "speech_balloon"]
        elif "github" in app_lower:
            return ["octocat"]
        else:
            return ["bell"]

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
