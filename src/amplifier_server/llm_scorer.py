"""LLM-based notification scoring using Amplifier."""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Default scoring prompt
SCORING_PROMPT = """You are an attention controller helping a busy professional manage \
notifications.

Given a notification, decide if it warrants immediate attention or can wait.

PRIORITIZE (score 0.7-1.0):
- Direct mentions of the user by name
- Deadlines, time-sensitive requests ("today", "ASAP", "urgent")
- Decisions being made that need input
- VIP senders (important colleagues, executives)
- Blocking issues or outages

MEDIUM PRIORITY (score 0.4-0.6):
- Work-related discussions that may need attention soon
- Meeting changes or calendar updates
- Questions that might be for the user

LOW PRIORITY (score 0.0-0.3):
- General chat/banter
- FYI messages with no action needed
- System notifications (updates, sync status)
- Marketing/promotional content

CONTEXT:
- User's name/aliases: {user_aliases}
- VIP senders: {vip_senders}
- Current time: {current_time}

NOTIFICATION:
- App: {app_name}
- From: {sender}
- Title: {title}
- Body: {body}
- Conversation: {conversation}

Respond with ONLY a JSON object (no markdown, no explanation):
{{"score": 0.0-1.0, "decision": "push|summarize|suppress", "rationale": "brief reason", \
"tags": ["tag1", "tag2"]}}

Rules:
- "push" = interrupt user now (score >= 0.6)
- "summarize" = include in next digest (score 0.3-0.6)  
- "suppress" = don't bother user (score < 0.3)
- If content seems truncated, be conservative unless VIP or deadline signals are clear
"""


@dataclass
class LLMScoringResult:
    """Result from LLM scoring."""

    score: float
    decision: str
    rationale: str
    tags: list[str]
    raw_response: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any], raw: str | None = None) -> "LLMScoringResult":
        return cls(
            score=float(data.get("score", 0.5)),
            decision=data.get("decision", "summarize"),
            rationale=data.get("rationale", "No rationale provided"),
            tags=data.get("tags", []),
            raw_response=raw,
        )

    @classmethod
    def fallback(cls, reason: str) -> "LLMScoringResult":
        """Create a fallback result when LLM fails."""
        return cls(
            score=0.5,
            decision="summarize",
            rationale=f"Fallback: {reason}",
            tags=["llm-fallback"],
        )


class LLMScorer:
    """Scores notifications using an Amplifier session.

    Uses LLM to evaluate notification importance with nuanced understanding.
    """

    def __init__(
        self,
        session_manager: Any,
        session_id: str | None = None,
        user_aliases: list[str] | None = None,
        vip_senders: list[str] | None = None,
    ):
        """Initialize the LLM scorer.

        Args:
            session_manager: SessionManager instance
            session_id: ID of session to use (will create if None)
            user_aliases: User's name/aliases for mention detection
            vip_senders: List of VIP senders
        """
        self.session_manager = session_manager
        self.session_id = session_id
        self.user_aliases = user_aliases or []
        self.vip_senders = vip_senders or []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the scoring session with minimal config.

        Uses a lightweight setup optimized for fast JSON scoring responses.
        """
        if self._initialized and self.session_id:
            return

        try:
            # Create a minimal session - just provider + orchestrator, no tools/hooks
            self.session_id = await self.session_manager.create_minimal_session(
                session_id="notification-scorer",
            )
            self._initialized = True
            logger.info(f"LLM scorer initialized with session: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM scorer: {e}")
            raise

    async def score(
        self,
        notification: dict[str, Any],
        current_time: str | None = None,
    ) -> LLMScoringResult:
        """Score a notification using the LLM.

        Args:
            notification: Notification data dict
            current_time: Current time string (for context)

        Returns:
            LLMScoringResult with score, decision, and rationale
        """
        if not self._initialized or not self.session_id:
            return LLMScoringResult.fallback("Scorer not initialized")

        # Build the prompt
        from datetime import datetime

        prompt = SCORING_PROMPT.format(
            user_aliases=", ".join(self.user_aliases) or "not specified",
            vip_senders=", ".join(self.vip_senders) or "none configured",
            current_time=current_time or datetime.now().strftime("%Y-%m-%d %H:%M"),
            app_name=notification.get("app_name") or notification.get("app_id", "Unknown"),
            sender=notification.get("sender", "Unknown"),
            title=notification.get("title", ""),
            body=notification.get("body", "")[:500],  # Limit body length
            conversation=notification.get("conversation_hint", ""),
        )

        try:
            # Execute in session
            response = await self.session_manager.execute(
                session_id=self.session_id,
                prompt=prompt,
            )

            # Parse JSON response
            result = self._parse_response(response)
            return result

        except Exception as e:
            logger.error(f"LLM scoring failed: {e}")
            return LLMScoringResult.fallback(str(e))

    def _parse_response(self, response: str) -> LLMScoringResult:
        """Parse LLM response into scoring result."""
        # Try to extract JSON from response
        response = response.strip()

        # Handle markdown code blocks
        if response.startswith("```"):
            lines = response.split("\n")
            # Remove first and last lines (```json and ```)
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            response = "\n".join(json_lines)

        # Try to find JSON object
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response[start:end]
            try:
                data = json.loads(json_str)
                return LLMScoringResult.from_json(data, response)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON: {e}")

        # Fallback if parsing fails
        return LLMScoringResult.fallback(f"Could not parse response: {response[:100]}")

    def update_config(
        self,
        user_aliases: list[str] | None = None,
        vip_senders: list[str] | None = None,
    ) -> None:
        """Update scorer configuration."""
        if user_aliases is not None:
            self.user_aliases = user_aliases
        if vip_senders is not None:
            self.vip_senders = vip_senders

    async def cleanup(self) -> None:
        """Cleanup the scoring session."""
        if self.session_id:
            try:
                await self.session_manager.stop_session(self.session_id)
            except Exception as e:
                logger.error(f"Error cleaning up scorer session: {e}")
