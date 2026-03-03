"""
Decision Engine - Thin Logic Layer
===================================
This decides state transitions based on current state, classification, and memory.
Rules:
- No text responses here
- Only state transitions

🛑 HARD RULE GOING FORWARD:
If a call type exists (with ANY confidence from smart classifier), bot asks for location.
The smart classifier already applies appropriate thresholds.
"""

from src.conversation.conversation_state import ConversationState
from src.conversation.case_memory import CaseMemory
from src.utils.helpers import (
    looks_like_location,
    is_confirmation,
    is_rejection,
)
from typing import Dict, Optional

# Very low threshold - smart classifier has already done the hard work
# This is a safety check, not the primary gate
MINIMUM_CLASSIFICATION_CONFIDENCE = 0.10


def decide_next_state(
    state: ConversationState,
    classification: Dict,
    memory: CaseMemory,
    user_text: Optional[str] = None
) -> ConversationState:
    """
    Decide the next conversation state based on current state, classification, and memory.
    
    Rules:
    - No text responses
    - Only state transitions
    - Trust the smart classifier's decisions
    """
    # Never leave SUBMITTED once a case is submitted
    if state == ConversationState.SUBMITTED:
        return ConversationState.SUBMITTED

    # Prevent infinite clarification loops (max 3 turns)
    if getattr(memory, "clarification_count", 0) >= 3 and state in (
        ConversationState.ISSUE_BUILDING,
        ConversationState.AWAITING_CLARIFICATION,
    ):
        return ConversationState.NEEDS_LOCATION
    # HARD RULE: If a call type exists, ask for location immediately.
    # The smart classifier has already applied appropriate confidence thresholds.
    
    # If we're in OPEN, check if we have a valid classification
    if state == ConversationState.OPEN:
        if user_text and _is_greeting_only(user_text):
            return ConversationState.OPEN
        # EARLY GUARD: If issue is already identified (any confidence), skip to NEEDS_LOCATION
        if classification.get("call_type_code") and (classification.get("confidence", 0.0) or 0) >= MINIMUM_CLASSIFICATION_CONFIDENCE:
            # Issue identified - go directly to location request
            return ConversationState.NEEDS_LOCATION
        return ConversationState.ISSUE_BUILDING
    
    # If we're in ISSUE_BUILDING and we have a classification
    if state == ConversationState.ISSUE_BUILDING:
        # EARLY GUARD: If issue is identified, skip clarification
        if classification.get("call_type_code") and (classification.get("confidence", 0.0) or 0) >= MINIMUM_CLASSIFICATION_CONFIDENCE:
            # We have an issue identified - need location immediately
            return ConversationState.NEEDS_LOCATION
        # Still building understanding (no classification)
        return ConversationState.ISSUE_BUILDING
    
    # If we're in NEEDS_LOCATION and user provided location
    if state == ConversationState.NEEDS_LOCATION:
        if memory.location:
            # We have location - move to confirmation
            return ConversationState.CONFIRMING
        # Check if user text looks like a location
        if user_text and looks_like_location(user_text):
            return ConversationState.CONFIRMING
        # Still need location
        return ConversationState.NEEDS_LOCATION
    
    # If we're confirming and user confirmed
    if state == ConversationState.CONFIRMING:
        if memory.confirmed:
            return ConversationState.SUBMITTED
        # Check if user text is a confirmation
        if user_text and is_confirmation(user_text):
            return ConversationState.SUBMITTED
        # Check if user text is a rejection
        if user_text and is_rejection(user_text):
            # Confirmation Contract: If user says "no", ticket MUST NOT be submitted
            # Bot MUST ask what to change (issue or location)
            # Go to a state where user can specify what to correct
            return ConversationState.ISSUE_BUILDING  # Allow correction
        # Still confirming
        return ConversationState.CONFIRMING
    
    # Default: stay in current state
    return state


def _is_greeting_only(text: str) -> bool:
    """Check if text is a greeting (with or without additional content)."""
    text_lower = text.strip().lower()
    
    # Exact greeting matches
    greeting_words = {
        "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
        "greetings", "howdy", "hallo", "howzit", "heita", "sawubona", "dumela",
        "molo", "hola", "yo", "sup", "ola"
    }
    
    if text_lower in greeting_words:
        return True
    
    # Check if message starts with a greeting
    for greeting in sorted(greeting_words, key=len, reverse=True):  # Check longer greetings first
        if text_lower.startswith(greeting):
            # Check what follows the greeting
            remainder = text_lower[len(greeting):].strip()
            # If nothing follows, or just punctuation/common words, it's a greeting
            if not remainder:
                return True
            # If it's just common follow-up words, still consider it a greeting
            common_followups = ["how are you", "how are", "how", "there", "what's up", "whats up"]
            if any(remainder.startswith(followup) for followup in common_followups):
                return True
            # If remainder is very short (1-2 words), likely still a greeting
            if len(remainder.split()) <= 2:
                return True
    
    return False


def _looks_like_location(text: str) -> bool:  # Backwards-compatible shim – use helpers.looks_like_location instead
    return looks_like_location(text)


def _is_confirmation(text: str) -> bool:  # Backwards-compatible shim – use helpers.is_confirmation instead
    return is_confirmation(text)


def _is_rejection(text: str) -> bool:  # Backwards-compatible shim – use helpers.is_rejection instead
    return is_rejection(text)
