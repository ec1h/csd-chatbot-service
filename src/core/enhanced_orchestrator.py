"""
EnhancedOrchestrator – Pure LLM response path.

No hardcoded templates. No location in response text.
The LLM writes every response; this class only routes on flags.

Activated when USE_ENHANCED_ORCHESTRATOR=true (default: false).
The existing orchestrator and all existing files remain untouched.
"""

import logging
from typing import Any, Dict, Optional

from src.llm.context_analyzer import ContextAnalyzer
from src.llm.retrieval import CallTypeRetriever
from src.conversation.context_memory import ContextMemory

logger = logging.getLogger(__name__)

_NEXT_ACTION_TO_STATE = {
    "request_location": "NEEDS_LOCATION",
    "ask_clarification": "AWAITING_CLARIFICATION",
    "confirm": "CONFIRMING",
    "send_response": "ISSUE_BUILDING",
}


class EnhancedOrchestrator:
    """LLM-driven orchestrator with retrieval-augmented context analysis."""

    def __init__(self, dspy_lm):
        self.retriever = CallTypeRetriever()
        self.analyzer = ContextAnalyzer(dspy_lm, self.retriever)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def process_message(
        self,
        message: str,
        session_id: str,
        memory: Optional[ContextMemory] = None,
        current_state: str = "OPEN",
    ) -> Dict[str, Any]:
        """Process a user message and return a response dict.

        The LLM decides every response.  This method only:
          1. Combines short follow-ups with prior context
          2. Calls the LLM analyzer
          3. Maps next_action → state
          4. Routes special intents (change_topic, change_location)

        Returns:
            {
              "response": str,           # pure LLM text, no templates
              "needs_location": bool,    # frontend shows map popup when True
              "selected_calltype": str | None,
              "state": str,
              "suggested_answers": list[str],
              "memory": dict,
            }
        """
        if memory is None:
            memory = ContextMemory()

        # ------------------------------------------------------------------
        # Short follow-up detection
        # Combine 1-3 word fragments with the last substantive user message
        # so the LLM has full context (e.g. "is rude" after "bus driver").
        # ------------------------------------------------------------------
        words = message.split()
        if len(words) <= 3 and memory.last_user_message:
            analysis_message = f"{memory.last_user_message} {message}"
            logger.info(
                "Short follow-up: %r → analysing as %r", message, analysis_message
            )
        else:
            analysis_message = message
            memory.last_user_message = message

        # ------------------------------------------------------------------
        # LLM analysis
        # ------------------------------------------------------------------
        recent_messages = memory.get_recent_messages(5)

        analysis = await self.analyzer.analyze(
            message=analysis_message,
            conversation_history=recent_messages,
            session_context={"session_id": session_id, "state": current_state},
        )

        memory.add_message("user", message, analysis)

        # ------------------------------------------------------------------
        # Extract guidance from LLM — NOTHING hardcoded below this line
        # ------------------------------------------------------------------
        intent = analysis.get("intent_analysis", {})
        guidance = analysis.get("conversation_guidance", {})
        issue = analysis.get("issue_extraction", {})
        primary_intent = intent.get("primary_intent", "unknown")

        # Response text MUST come from the LLM.
        response_text = guidance.get("response_text", "").strip()
        if not response_text:
            response_text = "Could you provide more details about the issue?"
            logger.error("LLM returned no response_text for: %r", message)

        needs_location = guidance.get("should_ask_location", False)
        next_action = guidance.get("next_action", "ask_clarification")

        # Map next_action → conversation state
        next_state = _NEXT_ACTION_TO_STATE.get(next_action, "ISSUE_BUILDING")

        # Override for confirm: only enter CONFIRMING if we already have a location.
        if next_action == "confirm" and not memory.location:
            next_state = "NEEDS_LOCATION"
            needs_location = True

        # Override for needs_location flag
        if next_state == "NEEDS_LOCATION":
            needs_location = True

        # ------------------------------------------------------------------
        # Special intent routing
        # ------------------------------------------------------------------
        if primary_intent == "change_topic":
            memory.reset_for_new_issue()
            next_state = "ISSUE_BUILDING"
            needs_location = False

        elif primary_intent == "change_location":
            next_state = "NEEDS_LOCATION"
            needs_location = True

        # ------------------------------------------------------------------
        # Finalise
        # ------------------------------------------------------------------
        memory.add_bot_message(response_text)

        # Best-confidence call type from LLM candidates
        selected_calltype_code = None
        selected_calltype_description = None
        best_confidence = 0.0
        classification_method = "llm"

        candidates = issue.get("call_type_candidates", [])
        if candidates:
            best = max(candidates, key=lambda c: c.get("confidence", 0))
            selected_calltype_code = best.get("code")
            selected_calltype_description = best.get("description")
            best_confidence = best.get("confidence", 0.0)
        elif memory.selected_call_type:
            selected_calltype_code = memory.selected_call_type.get("code")
            selected_calltype_description = memory.selected_call_type.get("description")
            best_confidence = memory.selected_call_type.get("confidence", 0.0)

        return {
            "response": response_text,
            "needs_location": needs_location,
            "chat_locked": next_state == "SUBMITTED",
            "classification": {
                "call_type_code": selected_calltype_code,
                "call_type_description": selected_calltype_description,
                "confidence": best_confidence,
                "method": classification_method,
            } if selected_calltype_code else None,
            "state": next_state,
            "suggested_answers": guidance.get("clarification_options", []),
            "frontend_flags": {
                "needs_location": needs_location,
                "show_map": needs_location,
                "conversation_done": next_state == "SUBMITTED",
                "chat_locked": next_state == "SUBMITTED",
            },
            "memory": memory.to_dict(),
        }

    # ------------------------------------------------------------------
    # Location handling
    # ------------------------------------------------------------------

    async def handle_location(
        self,
        location: str,
        session_id: str,
        memory: ContextMemory,
    ) -> Dict[str, Any]:
        """Accept a location from the frontend map picker.

        Passes a synthetic '[LOCATION PROVIDED: …]' turn to the LLM so it
        can write a natural confirmation message with full context.
        """
        memory.set_location(location)

        recent = memory.get_recent_messages(3)

        analysis = await self.analyzer.analyze(
            message=f"[LOCATION PROVIDED: {location}]",
            conversation_history=recent,
            session_context={"session_id": session_id, "state": "NEEDS_LOCATION"},
        )

        guidance = analysis.get("conversation_guidance", {})
        response_text = guidance.get("response_text", "").strip()
        if not response_text:
            response_text = "Location saved. Is everything correct?"
            logger.error("LLM returned no response_text for location: %r", location)

        memory.add_bot_message(response_text)

        ct_code = None
        ct_desc = None
        ct_conf = 0.0
        if memory.selected_call_type:
            ct_code = memory.selected_call_type.get("code")
            ct_desc = memory.selected_call_type.get("description")
            ct_conf = memory.selected_call_type.get("confidence", 0.0)

        return {
            "response": response_text,
            "needs_location": False,
            "chat_locked": False,
            "classification": {
                "call_type_code": ct_code,
                "call_type_description": ct_desc,
                "confidence": ct_conf,
                "method": "llm",
            } if ct_code else None,
            "state": "CONFIRMING",
            "suggested_answers": ["Yes, correct", "No — change location", "No — change issue"],
            "frontend_flags": {
                "needs_location": False,
                "show_map": False,
                "conversation_done": False,
                "chat_locked": False,
            },
            "memory": memory.to_dict(),
        }
