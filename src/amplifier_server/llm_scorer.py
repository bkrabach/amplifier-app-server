"""LLM-based notification scoring using Amplifier."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path for attention rules config
DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "attention-rules.md"

# Scoring framework prompt with autonomous config management
SCORING_FRAMEWORK = """You are an autonomous attention controller.

YOUR RULES (loaded from {rules_file}):
{custom_rules}

CURRENT CONTEXT:
- Time: {current_time}

AUTONOMOUS BEHAVIOR:
If your rules have time-based modes (e.g., "Active until 12:50 PM") and the current time 
indicates you should switch modes, use write_file to update {rules_file} BEFORE scoring.

Then score this notification according to the active rules.

NOTIFICATION TO SCORE:
- App: {app_name}
- From: {sender}
- Title: {title}
- Body: {body}

SCORING OUTPUT (required JSON):
{{"score": 0.0-1.0, "decision": "push|summarize|suppress", "rationale": "brief reason", "tags": ["tag1"]}}

Thresholds: push >= 0.6, summarize 0.3-0.6, suppress < 0.3

Respond with ONLY the JSON object.
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
        """Load custom rules from markdown file."""
        try:
            if self.rules_path.exists():
                self._custom_rules = self.rules_path.read_text()
                logger.info(f"Loaded {len(self._custom_rules)} chars of rules from {self.rules_path}")
            else:
                logger.warning(f"Rules file not found: {self.rules_path}")
                self._custom_rules = ""
        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            self._custom_rules = ""

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

        # Build the prompt - reload rules each time
        from datetime import datetime

        self._load_rules()  # Reload from disk
        
        prompt = SCORING_FRAMEWORK.format(
            rules_file=str(self.rules_path),
            custom_rules=self._custom_rules or "No rules loaded",
            current_time=current_time or datetime.now().strftime("%Y-%m-%d %I:%M %p %A"),
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
            await self._reset_context()

            return result

        except Exception as e:
            logger.error(f"LLM scoring failed: {e}")
            return LLMScoringResult.fallback(str(e))

    async def _reset_context(self) -> None:
        """Reset session context to keep scoring stateless."""
        try:
            await self.session_manager.clear_context(self.session_id)
            logger.debug("Context cleared")
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
