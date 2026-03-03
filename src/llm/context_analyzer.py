"""
LLM-based context analyzer with structured output.

Accepts a DSPy LM instance (``dspy.LM``) and a ``CallTypeRetriever``,
builds a prompt from conversation history + retrieved candidates, calls
the LLM, and parses the structured JSON response.

The ``dspy.LM.__call__`` method is synchronous; this module wraps it
with ``asyncio.to_thread`` so it can be awaited from async handlers.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "context_analyzer.txt")


class ContextAnalyzer:
    def __init__(self, dspy_lm, retriever):
        self.lm = dspy_lm
        self.retriever = retriever
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        with open(_PROMPT_PATH, "r") as f:
            return f.read()

    def strip_location_from_issue(self, text: str) -> str:
        """Remove trailing location phrases from issue text.

        Location is collected exclusively via the frontend popup; it must
        never bleed into the issue description used for classification.
        """
        location_patterns = [
            r"\s+on\s+the\s+road$",
            r"\s+at\s+\d+\s+.*$",
            r"\s+in\s+\w+\s+street$",
            r"\s+near\s+.*$",
            r"\s+outside\s+.*$",
            r"\s+inside\s+.*$",
            r"\s+by\s+.*$",
        ]
        clean = text
        for pattern in location_patterns:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)
        return clean.strip()

    def _format_history(self, messages: List[Dict]) -> str:
        """Format the last 5 messages for the prompt."""
        if not messages:
            return "No previous messages."
        lines = []
        for msg in messages[-5:]:
            role = "User" if msg.get("role") == "user" else "Bot"
            lines.append(f"{role}: {msg.get('content', '')}")
        return "\n".join(lines)

    async def analyze(
        self,
        message: str,
        conversation_history: List[Dict],
        session_context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Analyze *message* with full context and return a structured dict."""
        # Strip location phrases before retrieval so they don't influence
        # call-type matching.  The original message stays in conversation history
        # (added by the orchestrator); only the cleaned version is used here.
        clean_message = self.strip_location_from_issue(message)

        candidates = self.retriever.retrieve(clean_message, top_k=10)
        candidate_text = self.retriever.format_candidates_for_llm(candidates)
        history_text = self._format_history(conversation_history)

        prompt = self.prompt_template.format(
            conversation_history=history_text,
            current_message=clean_message,
            candidate_call_types=candidate_text,
        )

        try:
            # dspy.LM is synchronous – run in thread pool to keep caller async
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_lm, prompt),
                timeout=10.0,
            )
            result = self._parse_json_response(response)

            if not self._validate_result(result):
                logger.warning("LLM result missing required sections – using fallback")
                return self._get_fallback_analysis(message)

            result["_retrieved_candidates"] = candidates
            return result

        except asyncio.TimeoutError:
            logger.error("LLM call timed out for context analysis")
            return self._get_fallback_analysis(message)
        except Exception as exc:
            logger.exception("LLM context analysis error: %s", exc)
            return self._get_fallback_analysis(message)

    def _call_lm(self, prompt: str) -> str:
        """Synchronous wrapper around dspy.LM to run in a thread."""
        responses = self.lm(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        # dspy.LM returns a list of completions
        if isinstance(responses, list) and responses:
            return responses[0]
        return str(responses)

    def _parse_json_response(self, response: str) -> Dict:
        """Extract JSON from the LLM response text."""
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except Exception:
                pass
        try:
            return json.loads(response)
        except Exception:
            logger.error("Failed to parse LLM response: %s", response[:200])
            return {}

    def _validate_result(self, result: Dict) -> bool:
        required = [
            "intent_analysis",
            "issue_extraction",
            "conversation_guidance",
            "context_aggregation",
            "rephrased_user_input",
        ]
        return all(section in result for section in required)

    def _get_fallback_analysis(self, message: str) -> Dict[str, Any]:
        """Safe fallback when the LLM is unavailable or returns malformed output."""
        domain_keywords = {
            "water", "electricity", "roads", "waste", "transport",
            "bus", "metro", "sewer", "power", "light", "street",
        }
        message_lower = message.lower().strip()
        words = message_lower.split()
        filler_words = {"the", "my", "with", "issue", "problem", "a", "an", "some"}
        is_domain_only = (
            len(words) <= 3
            and all(w in domain_keywords or w in filler_words for w in words)
        )

        if is_domain_only:
            main_domain = next((w for w in words if w in domain_keywords), message_lower)
            return {
                "intent_analysis": {
                    "primary_intent": "report_problem",
                    "confidence": 0.5,
                    "detected_domains": [main_domain],
                    "is_vague": True,
                    "vagueness_reason": "User only specified domain without describing problem",
                },
                "issue_extraction": {
                    "extracted_issue": message,
                    "issue_summary": None,
                    "call_type_candidates": [],
                    "missing_critical_info": ["specific problem description"],
                },
                "conversation_guidance": {
                    "next_action": "ask_clarification",
                    "response_text": (
                        f"What {main_domain} issue are you experiencing? "
                        f"For example, did a bus not arrive, is there no water, or something else?"
                    ),
                    "clarification_question": f"What specific {main_domain} problem are you reporting?",
                    "clarification_options": [],
                    "should_ask_location": False,
                },
                "context_aggregation": {
                    "accumulated_details": [f"user mentioned {main_domain}"],
                    "still_needs": ["specific problem description"],
                    "conversation_progress": 0.1,
                },
                "rephrased_user_input": message,
            }

        return {
            "intent_analysis": {
                "primary_intent": "unknown",
                "confidence": 0.1,
                "detected_domains": [],
                "is_vague": True,
                "vagueness_reason": "LLM unavailable",
            },
            "issue_extraction": {
                "extracted_issue": message,
                "issue_summary": message,
                "call_type_candidates": [],
                "missing_critical_info": ["details"],
            },
            "conversation_guidance": {
                "next_action": "ask_clarification",
                "response_text": "Could you provide more details about the issue?",
                "clarification_question": "Could you provide more details about the issue?",
                "clarification_options": [],
                "should_ask_location": False,
            },
            "context_aggregation": {
                "accumulated_details": [message],
                "still_needs": ["specific details"],
                "conversation_progress": 0.1,
            },
            "rephrased_user_input": message,
        }
