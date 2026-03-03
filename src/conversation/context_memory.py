"""
ContextMemory – cross-turn conversation tracking for the enhanced orchestrator.

Distinct from CaseMemory (src/conversation/case_memory.py) which is used by
the existing orchestrator.  ContextMemory is used exclusively by
EnhancedOrchestrator and accumulates structured LLM-analysis results across
turns so the next turn's prompt benefits from everything learned so far.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextMemory:
    """Accumulates analysis results and conversation facts across turns."""

    def __init__(self):
        self.messages: List[Dict] = []
        self.accumulated_details: List[str] = []
        self.extracted_issues: List[str] = []
        self.missing_info: List[str] = []
        self.current_issue_summary: Optional[str] = None
        self.call_type_candidates: List[Dict] = []
        self.selected_call_type: Optional[Dict] = None
        self.location: Optional[str] = None
        self.vagueness_count: int = 0
        self.clarification_count: int = 0
        self.last_llm_analysis: Optional[Dict] = None
        self.last_user_message: Optional[str] = None

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Pronoun resolution
    # ------------------------------------------------------------------

    def resolve_pronouns(self, current_message: str) -> str:
        """Resolve short follow-up messages by prepending the last user message.

        If the current message is 1–3 words and contains a pronoun or starts
        with a verb/adjective fragment (e.g. "is rude", "he was late"),
        combine it with the previous user message so the LLM has full context.
        """
        words = current_message.strip().split()
        if len(words) > 3 or not self.last_user_message:
            return current_message

        pronouns = {"it", "he", "she", "they", "him", "her", "them", "the",
                    "is", "was", "are", "were", "has", "have"}
        has_fragment_start = words[0].lower() in pronouns

        if has_fragment_start:
            combined = f"{self.last_user_message} {current_message}"
            logger.info(
                "Pronoun/fragment resolution: %r → %r", current_message, combined
            )
            return combined

        return current_message

    def add_message(
        self,
        role: str,
        content: str,
        analysis: Optional[Dict] = None,
    ) -> None:
        """Append a user or bot message, optionally integrating LLM analysis."""
        if role == "user":
            resolved_content = self.resolve_pronouns(content)
            if resolved_content != content:
                content = resolved_content
            # Only update last_user_message for substantive messages (>3 words)
            if len(content.split()) > 3:
                self.last_user_message = content

        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "analysis": analysis,
            }
        )
        if analysis:
            self._integrate_analysis(analysis)

    def add_bot_message(self, content: str) -> None:
        """Convenience wrapper for bot responses."""
        self.messages.append(
            {
                "role": "bot",
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        )

    # ------------------------------------------------------------------
    # Analysis integration
    # ------------------------------------------------------------------

    def _integrate_analysis(self, analysis: Dict) -> None:
        """Extract and accumulate information from a single LLM analysis result."""
        self.last_llm_analysis = analysis

        context = analysis.get("context_aggregation", {})
        for detail in context.get("accumulated_details", []):
            if detail not in self.accumulated_details:
                self.accumulated_details.append(detail)

        self.missing_info = context.get("still_needs", [])

        issue = analysis.get("issue_extraction", {})
        if issue.get("issue_summary"):
            self.current_issue_summary = issue["issue_summary"]

        candidates = issue.get("call_type_candidates", [])
        if candidates:
            self.call_type_candidates = candidates
            self.selected_call_type = max(
                candidates, key=lambda x: x.get("confidence", 0)
            )

        intent = analysis.get("intent_analysis", {})
        if intent.get("is_vague"):
            self.vagueness_count += 1

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def set_selected_call_type(self, call_type_dict: Dict) -> None:
        """Store both code and description for the selected call type."""
        self.selected_call_type = {
            "code": call_type_dict.get("code"),
            "description": call_type_dict.get("description"),
            "confidence": call_type_dict.get("confidence", 0.0),
        }

    def set_location(self, location: str) -> None:
        """Store the user's reported location."""
        self.location = location
        if "address" in self.missing_info:
            self.missing_info.remove("address")

    # ------------------------------------------------------------------
    # Resets
    # ------------------------------------------------------------------

    def reset_for_new_issue(self) -> None:
        """Clear issue-specific state while preserving conversation history."""
        self.accumulated_details = []
        self.extracted_issues = []
        self.current_issue_summary = None
        self.call_type_candidates = []
        self.selected_call_type = None
        self.vagueness_count = 0
        self.clarification_count = 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_messages(self, count: int = 5) -> List[Dict]:
        """Return the last *count* messages."""
        return self.messages[-count:]

    def get_conversation_context(self) -> str:
        """Format accumulated details as a summary string."""
        if not self.accumulated_details:
            return "No details gathered yet."
        lines = ["Known information:"]
        for detail in self.accumulated_details:
            lines.append(f"- {detail}")
        if self.location:
            lines.append(f"- Location: {self.location}")
        if self.missing_info:
            lines.append("\nStill need:")
            for info in self.missing_info:
                lines.append(f"- {info}")
        return "\n".join(lines)

    def should_proceed_to_location(self) -> bool:
        """True when we know enough to ask for a location."""
        return (
            self.selected_call_type is not None
            and self.current_issue_summary is not None
            and self.vagueness_count < 3
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dict (keeps last 20 messages)."""
        return {
            "messages": self.messages[-20:],
            "accumulated_details": self.accumulated_details,
            "current_issue_summary": self.current_issue_summary,
            "selected_call_type": self.selected_call_type,
            "call_type_candidates": self.call_type_candidates,
            "missing_info": self.missing_info,
            "location": self.location,
            "vagueness_count": self.vagueness_count,
            "clarification_count": self.clarification_count,
            "last_user_message": self.last_user_message,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ContextMemory":
        """Deserialise from a stored dict."""
        memory = cls()
        memory.messages = data.get("messages", [])
        memory.accumulated_details = data.get("accumulated_details", [])
        memory.current_issue_summary = data.get("current_issue_summary")
        memory.selected_call_type = data.get("selected_call_type")
        memory.call_type_candidates = data.get("call_type_candidates", [])
        memory.missing_info = data.get("missing_info", [])
        memory.location = data.get("location")
        memory.vagueness_count = data.get("vagueness_count", 0)
        memory.clarification_count = data.get("clarification_count", 0)
        memory.last_user_message = data.get("last_user_message")
        return memory
