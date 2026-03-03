"""
Conversation State Enum - Foundation Layer
==========================================
This file defines the conversation states that control the flow.
It must NEVER import:
- LLM code
- Classifiers
- Databases
"""

from enum import Enum


class ConversationState(Enum):
    """Conversation states that control the flow independently of classification quality."""
    OPEN = "open"
    ISSUE_BUILDING = "issue_building"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    NEEDS_LOCATION = "needs_location"
    CONFIRMING = "confirming"
    SUBMITTED = "submitted"


class ConversationPhase:
    """Legacy conversation phase constants for backward compatibility."""
    OPEN_INTAKE = "OPEN_INTAKE"
    PROBLEM_NARROWING = "PROBLEM_NARROWING"
    DETAIL_COLLECTION = "DETAIL_COLLECTION"
    CONFIRMATION = "CONFIRMATION"
    LOCKED_FOR_SUBMISSION = "LOCKED_FOR_SUBMISSION"
