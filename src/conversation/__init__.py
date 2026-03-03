"""
Conversation module for CSD Chatbot.

Contains:
- conversation_state: ConversationState enum and ConversationPhase
- case_memory: CaseMemory dataclass for tracking conversation
- decision_engine: State transition logic
- response_generator: Human-readable response generation
- frontend_signals: State-based frontend flags
- issue_summary_builder: Deterministic issue summary construction
"""

from src.conversation.conversation_state import ConversationState, ConversationPhase
from src.conversation.case_memory import CaseMemory
from src.conversation.decision_engine import decide_next_state
from src.conversation.response_generator import generate_response
from src.conversation.frontend_signals import get_frontend_flags
from src.conversation.issue_summary_builder import build_submission_summary

__all__ = [
    "ConversationState",
    "ConversationPhase",
    "CaseMemory",
    "decide_next_state",
    "generate_response",
    "get_frontend_flags",
    "build_submission_summary",
]
