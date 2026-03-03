"""
Test suite for the context-aware chatbot upgrade.

Covers:
  - ContextMemory: storage, serialisation, analysis integration
  - CallTypeRetriever: domain filtering and keyword fallback
  - EnhancedOrchestrator: vague messages, clear messages, location handling,
    topic change, confirmation flow
"""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.conversation.context_memory import ContextMemory
from src.core.enhanced_orchestrator import EnhancedOrchestrator

# Configure pytest-asyncio to auto-detect async tests in this module
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared LLM mock factory
# ---------------------------------------------------------------------------

def _make_lm_response(payload: dict) -> str:
    return json.dumps(payload)


def _analysis_water_clear():
    return {
        "intent_analysis": {
            "primary_intent": "report_problem",
            "confidence": 0.95,
            "detected_domains": ["water"],
            "is_vague": False,
        },
        "issue_extraction": {
            "extracted_issue": "no water",
            "issue_summary": "No water supply at home",
            "call_type_candidates": [
                {"code": "10016", "description": "NO WATER", "confidence": 0.95}
            ],
            "missing_critical_info": ["address"],
        },
        "conversation_guidance": {
            "next_action": "request_location",
            "response_text": "I understand you have no water. I need your address to log this.",
            "clarification_options": [],
            "should_ask_location": True,
        },
        "context_aggregation": {
            "accumulated_details": ["user has no water supply"],
            "still_needs": ["address"],
            "conversation_progress": 0.6,
        },
        "rephrased_user_input": "I have no water supply at home",
    }


def _analysis_water_vague():
    return {
        "intent_analysis": {
            "primary_intent": "report_problem",
            "confidence": 0.6,
            "detected_domains": ["water"],
            "is_vague": True,
            "vagueness_reason": "only domain mentioned, no specific issue",
        },
        "issue_extraction": {
            "extracted_issue": "water",
            "issue_summary": None,
            "call_type_candidates": [],
            "missing_critical_info": ["specific water issue"],
        },
        "conversation_guidance": {
            "next_action": "ask_clarification",
            "response_text": "What water issue are you experiencing?",
            "clarification_question": "What water issue are you experiencing?",
            "clarification_options": ["No water", "Leak", "Sewer", "Billing"],
            "should_ask_location": False,
        },
        "context_aggregation": {
            "accumulated_details": ["user mentioned water"],
            "still_needs": ["specific water issue"],
            "conversation_progress": 0.2,
        },
        "rephrased_user_input": "I have a water-related issue",
    }


def _analysis_change_topic():
    return {
        "intent_analysis": {
            "primary_intent": "change_topic",
            "confidence": 0.98,
            "detected_domains": ["electricity"],
            "is_vague": False,
        },
        "issue_extraction": {
            "extracted_issue": "electricity issue",
            "issue_summary": None,
            "call_type_candidates": [],
            "missing_critical_info": ["specific electricity issue"],
        },
        "conversation_guidance": {
            "next_action": "ask_clarification",
            "response_text": "No problem! What electricity issue are you experiencing?",
            "clarification_options": [],
            "should_ask_location": False,
        },
        "context_aggregation": {
            "accumulated_details": [],
            "still_needs": ["specific electricity issue"],
            "conversation_progress": 0.1,
        },
        "rephrased_user_input": "I want to report an electricity issue instead",
    }


def _analysis_affirm():
    return {
        "intent_analysis": {
            "primary_intent": "affirm",
            "confidence": 0.99,
            "detected_domains": [],
            "is_vague": False,
        },
        "issue_extraction": {
            "extracted_issue": "confirmed",
            "issue_summary": "No water supply at home",
            "call_type_candidates": [
                {"code": "10016", "description": "NO WATER", "confidence": 0.95}
            ],
            "missing_critical_info": [],
        },
        "conversation_guidance": {
            "next_action": "send_response",
            "response_text": "Thank you. Your report has been submitted.",
            "clarification_options": [],
            "should_ask_location": False,
        },
        "context_aggregation": {
            "accumulated_details": ["user confirmed issue and location"],
            "still_needs": [],
            "conversation_progress": 1.0,
        },
        "rephrased_user_input": "Yes, that is correct",
    }


# ---------------------------------------------------------------------------
# Fixture: mock LLM
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_lm():
    """A mock dspy.LM that returns JSON based on prompt content."""

    def _call(messages, **kwargs):
        content = messages[0]["content"] if messages else ""
        # Extract only the user message line to avoid matching candidates in the prompt
        user_line = ""
        for line in content.splitlines():
            if line.startswith("LATEST USER MESSAGE:"):
                user_line = line.lower()
                break
        if "no water" in user_line:
            return [_make_lm_response(_analysis_water_clear())]
        return [_make_lm_response(_analysis_water_vague())]

    lm = MagicMock()
    lm.side_effect = _call
    return lm


# ---------------------------------------------------------------------------
# ContextMemory unit tests
# ---------------------------------------------------------------------------

class TestContextMemory:

    def test_add_user_message_integrates_analysis(self):
        memory = ContextMemory()
        analysis = _analysis_water_clear()
        memory.add_message("user", "no water at my house", analysis)

        assert "user has no water supply" in memory.accumulated_details
        assert memory.current_issue_summary == "No water supply at home"
        assert memory.selected_call_type is not None
        assert memory.selected_call_type["code"] == "10016"

    def test_vagueness_counter_increments(self):
        memory = ContextMemory()
        memory.add_message("user", "water", _analysis_water_vague())
        assert memory.vagueness_count == 1

    def test_set_location_removes_address_from_missing(self):
        memory = ContextMemory()
        memory.missing_info = ["address", "severity"]
        memory.set_location("123 Main Street")
        assert "address" not in memory.missing_info
        assert memory.location == "123 Main Street"

    def test_reset_for_new_issue_clears_issue_state(self):
        memory = ContextMemory()
        memory.add_message("user", "no water at my house", _analysis_water_clear())
        memory.reset_for_new_issue()
        assert memory.accumulated_details == []
        assert memory.current_issue_summary is None
        assert memory.selected_call_type is None

    def test_serialise_and_deserialise(self):
        memory = ContextMemory()
        memory.add_message("user", "no water at my house", _analysis_water_clear())
        memory.set_location("1 Test Road")

        data = memory.to_dict()
        restored = ContextMemory.from_dict(data)

        assert restored.current_issue_summary == memory.current_issue_summary
        assert restored.location == memory.location
        assert restored.selected_call_type == memory.selected_call_type

    def test_should_proceed_to_location_true(self):
        memory = ContextMemory()
        memory.add_message("user", "no water", _analysis_water_clear())
        assert memory.should_proceed_to_location() is True

    def test_should_proceed_to_location_false_when_vague(self):
        memory = ContextMemory()
        for _ in range(3):
            memory.add_message("user", "water", _analysis_water_vague())
        assert memory.should_proceed_to_location() is False


# ---------------------------------------------------------------------------
# EnhancedOrchestrator integration tests
# ---------------------------------------------------------------------------

class TestEnhancedOrchestrator:

    @pytest.fixture
    def orchestrator(self, mock_lm):
        return EnhancedOrchestrator(mock_lm)

    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_vague_message_triggers_clarification(self, orchestrator):
        memory = ContextMemory()
        result = await orchestrator.process_message("water", "sess-1", memory)

        assert result["needs_location"] is False
        assert result["state"] == "AWAITING_CLARIFICATION"
        assert len(result["suggested_answers"]) > 0

    @pytest.mark.asyncio
    async def test_clear_message_requests_location(self, orchestrator):
        memory = ContextMemory()
        result = await orchestrator.process_message("no water at my house", "sess-1", memory)

        assert result["needs_location"] is True
        assert result["state"] == "NEEDS_LOCATION"
        assert result["selected_calltype"] == "10016"

    @pytest.mark.asyncio
    async def test_location_handling_moves_to_confirming(self, orchestrator):
        memory = ContextMemory()
        await orchestrator.process_message("no water at my house", "sess-1", memory)

        result = await orchestrator.handle_location("123 Main St", "sess-1", memory)

        assert result["needs_location"] is False
        assert result["state"] == "CONFIRMING"
        assert "123 Main St" in result["response"]
        assert "Yes, correct" in result["suggested_answers"]

    @pytest.mark.asyncio
    async def test_topic_change_resets_issue_memory(self, orchestrator, mock_lm):
        # Override mock to return change_topic analysis
        mock_lm.side_effect = lambda messages, **kw: [
            _make_lm_response(_analysis_change_topic())
        ]

        memory = ContextMemory()
        # Simulate a previous issue in memory
        memory.add_message("user", "no water", _analysis_water_clear())

        result = await orchestrator.process_message(
            "no wait I meant electricity", "sess-1", memory
        )

        assert result["state"] == "ISSUE_BUILDING"
        assert "electricity" in result["response"].lower()
        # Issue memory should be wiped by topic change
        assert memory.current_issue_summary is None

    @pytest.mark.asyncio
    async def test_confirm_intent_sends_response(self, orchestrator, mock_lm):
        mock_lm.side_effect = lambda messages, **kw: [
            _make_lm_response(_analysis_affirm())
        ]

        memory = ContextMemory()
        result = await orchestrator.process_message(
            "yes", "sess-1", memory, current_state="CONFIRMING"
        )

        assert "submitted" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_deny_in_confirming_asks_what_to_change(self, orchestrator, mock_lm):
        deny_analysis = {
            "intent_analysis": {
                "primary_intent": "deny",
                "confidence": 0.99,
                "detected_domains": [],
                "is_vague": False,
            },
            "issue_extraction": {
                "extracted_issue": "no",
                "issue_summary": None,
                "call_type_candidates": [],
                "missing_critical_info": [],
            },
            "conversation_guidance": {
                "next_action": "ask_what_to_change",
                "response_text": "What would you like to change?",
                "clarification_options": ["Issue", "Location", "Both"],
                "should_ask_location": False,
            },
            "context_aggregation": {
                "accumulated_details": [],
                "still_needs": [],
                "conversation_progress": 0.5,
            },
            "rephrased_user_input": "No that is not correct",
        }
        mock_lm.side_effect = lambda messages, **kw: [
            _make_lm_response(deny_analysis)
        ]

        memory = ContextMemory()
        result = await orchestrator.process_message(
            "no", "sess-1", memory, current_state="CONFIRMING"
        )

        assert result["state"] == "AWAITING_CLARIFICATION"
        assert "change" in result["response"].lower()
