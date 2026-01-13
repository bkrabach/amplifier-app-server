"""LLM-based notification scoring using Amplifier."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path for attention rules config
DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "attention-rules.md"

# Default scoring prompt with custom rules placeholder
SCORING_PROMPT = """You are an attention controller helping a busy professional manage \
notifications.

Given a notification, decide if it warrants immediate attention or can wait.

BASELINE PRIORITY GUIDELINES:

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

{custom_rules}

CONTEXT:
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
- Custom rules above OVERRIDE baseline guidelines when they conflict
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
    Supports custom rules via markdown config file.
    """

    def __init__(
        self,
        session_manager: Any,
        session_id: str | None = None,
        rules_path: Path | str | None = None,
    ):
        """Initialize the LLM scorer.

        Args:
            session_manager: SessionManager instance
            session_id: ID of session to use (will create if None)
            rules_path: Path to custom rules markdown file (optional)
        """
        self.session_manager = session_manager
        self.session_id = session_id
        self.rules_path = Path(rules_path) if rules_path else DEFAULT_RULES_PATH
        self._custom_rules: str = ""
        self._initialized = False

        # Load rules on init
        self._load_rules()

    def _load_rules(self) -> None:
        """Load custom rules from the config file.

        Rules are stored in a markdown file and injected into the scoring prompt.
        If the file doesn't exist or can't be read, scoring continues with
        baseline rules only.
        """
        if self.rules_path and self.rules_path.exists():
            try:
                self._custom_rules = self.rules_path.read_text(encoding="utf-8")
                logger.info(f"Loaded attention rules from {self.rules_path}")
            except Exception as e:
                logger.warning(f"Failed to load rules from {self.rules_path}: {e}")
                self._custom_rules = ""
        else:
            logger.info(f"No rules file at {self.rules_path}, using baseline rules only")
            self._custom_rules = ""

    def reload_rules(self) -> None:
        """Reload rules from the config file.

        Call this to pick up changes to the rules file without restarting.
        """
        self._load_rules()

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

        # Build the prompt with custom rules
        from datetime import datetime

        # Format custom rules section
        rules_section = ""
        if self._custom_rules:
            rules_section = (
                f"USER-SPECIFIC RULES (take precedence over baseline):\n\n{self._custom_rules}"
            )

        prompt = SCORING_PROMPT.format(
            custom_rules=rules_section,
            current_time=current_time or datetime.now().strftime("%Y-%m-%d %H:%M %A"),
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

            # Clear context after scoring to keep it stateless
            # Each scoring should be independent with no accumulated history
            await self._reset_context()

            return result

        except Exception as e:
            logger.error(f"LLM scoring failed: {e}")
            # Still try to clear context on error to prevent accumulation
            await self._reset_context()
            return LLMScoringResult.fallback(str(e))

    async def _reset_context(self) -> None:
        """Reset session context to keep scoring stateless.

        Each notification should be scored independently without
        context from previous notifications affecting the decision.
        """
        if self.session_id:
            try:
                await self.session_manager.clear_context(self.session_id)
            except Exception as e:
                logger.warning(f"Failed to clear context: {e}")

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
        rules_path: Path | str | None = None,
    ) -> None:
        """Update scorer configuration.

        Args:
            rules_path: New path to rules file (optional, reloads current if None)
        """
        if rules_path is not None:
            self.rules_path = Path(rules_path)
        self._load_rules()

    async def cleanup(self) -> None:
        """Cleanup the scoring session."""
        if self.session_id:
            try:
                await self.session_manager.stop_session(self.session_id)
            except Exception as e:
                logger.error(f"Error cleaning up scorer session: {e}")
