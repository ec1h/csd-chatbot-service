"""
Slot-Based Clarification System
================================
This module implements the slot-based clarification approach from the Behavior Contract.

Instead of asking generic "tell me more" questions, we ask for specific missing
information (slots) that help narrow down to the correct call type.

Key Concepts:
- Each call type may have required slots (duration, facility_type, severity, etc.)
- Clarification questions target missing slots
- Rare call types become reachable through slot collection
- All call types stay "alive" as candidates until slots rule them out
"""

from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


# Define slot types and their possible values
SLOT_DEFINITIONS = {
    "duration": {
        "type": "categorical",
        "values": ["just_now", "hours", "days", "weeks", "ongoing"],
        "question": "How long has this been happening? Just now, for hours, days, weeks, or is it ongoing?",
    },
    "facility_type": {
        "type": "categorical",
        "values": ["bus", "bus_stop", "clinic", "hospital", "park", "playground", "public_building"],
        "question": "Where exactly is this? Is it on a bus, at a bus stop, in a clinic, hospital, park, or another public area?",
    },
    "severity": {
        "type": "categorical",
        "values": ["minor", "moderate", "severe", "urgent"],
        "question": "How severe is this? Is it minor, moderate, severe, or urgent?",
    },
    "time_of_day": {
        "type": "categorical",
        "values": ["day", "night", "always"],
        "question": "When does this happen? During the day, at night, or all the time?",
    },
    "number_affected": {
        "type": "numeric",
        "values": ["one", "few", "many", "all"],
        "question": "How many are affected? Just one, a few, many, or all of them?",
    },
}


# Define which call types require which slots
# This helps narrow down from candidates to the correct call type
CALL_TYPE_SLOTS = {
    # Transport cleanliness issues
    "25018": {  # Dirty bus seats
        "required": ["facility_type"],
        "optional": ["severity", "number_affected"],
    },
    # Streetlight issues
    "11003": {  # Street light fault
        "required": ["time_of_day"],
        "optional": ["number_affected"],
    },
    # Water supply issues
    "10005": {  # No water supply
        "required": ["duration"],
        "optional": ["severity"],
    },
    # Default for unknown call types - keep minimal
    # Duration/severity should only be asked for genuinely ambiguous cases
    "default": {
        "required": [],
        "optional": ["duration", "severity"],
    },
}


def get_required_slots(call_type_code: Optional[int]) -> List[str]:
    """
    Get required slots for a specific call type.
    
    Args:
        call_type_code: Call type code
        
    Returns:
        List of required slot names
    """
    if not call_type_code:
        return []
    
    code_str = str(call_type_code)
    slot_config = CALL_TYPE_SLOTS.get(code_str, CALL_TYPE_SLOTS["default"])
    return slot_config.get("required", [])


def get_missing_slots(
    candidates: List[Dict[str, Any]],
    collected_slots: Dict[str, Any]
) -> List[str]:
    """
    Determine which slots are still missing based on current candidates.
    
    Args:
        candidates: List of candidate call types
        collected_slots: Slots already collected
        
    Returns:
        List of missing slot names (prioritized by importance)
    """
    if not candidates:
        return []
    
    # Collect all required slots from top candidates
    all_required: Dict[str, int] = {}  # slot_name -> count of candidates needing it
    
    for candidate in candidates[:5]:  # Check top 5 candidates
        code = candidate.get("call_type_code")
        if not code:
            continue
        
        required = get_required_slots(code)
        for slot in required:
            if slot not in collected_slots:
                all_required[slot] = all_required.get(slot, 0) + 1
    
    if not all_required:
        return []
    
    # Sort by how many candidates need each slot (most needed first)
    sorted_slots = sorted(all_required.items(), key=lambda x: x[1], reverse=True)
    return [slot for slot, _ in sorted_slots]


def generate_slot_question(slot_name: str) -> str:
    """
    Generate a clarification question for a specific slot.
    
    Args:
        slot_name: Name of the slot to ask about
        
    Returns:
        Clarification question
    """
    slot_def = SLOT_DEFINITIONS.get(slot_name)
    if not slot_def:
        return "Can you provide more details?"
    
    return slot_def.get("question", "Can you tell me more?")


def extract_slot_value(slot_name: str, user_text: str) -> Optional[Any]:
    """
    Extract slot value from user's response.
    
    Args:
        slot_name: Name of the slot
        user_text: User's message
        
    Returns:
        Extracted value or None
    """
    slot_def = SLOT_DEFINITIONS.get(slot_name)
    if not slot_def:
        return None
    
    text_lower = user_text.lower()
    values = slot_def.get("values", [])
    
    # Simple keyword matching for categorical slots
    if slot_def.get("type") == "categorical":
        for value in values:
            value_keywords = value.replace("_", " ").split()
            if any(kw in text_lower for kw in value_keywords):
                return value
    
    # For numeric slots, look for numbers or categorical descriptions
    elif slot_def.get("type") == "numeric":
        for value in values:
            if value in text_lower:
                return value
    
    # If we can't extract a specific value, return the user's text as-is
    # This allows manual interpretation later
    return user_text


def filter_candidates_by_slot(
    candidates: List[Dict[str, Any]],
    slot_name: str,
    slot_value: Any
) -> List[Dict[str, Any]]:
    """
    Filter candidates based on collected slot value.
    
    This helps narrow down the candidate list as we collect more information.
    
    Args:
        candidates: Current candidate list
        slot_name: Slot name that was collected
        slot_value: Value collected for the slot
        
    Returns:
        Filtered list of candidates
    """
    # For now, we keep all candidates
    # In a more advanced implementation, we would filter based on slot compatibility
    # Example: if facility_type="bus", filter out call types that don't apply to buses
    
    logger.info(f"Slot collected: {slot_name}={slot_value}, candidates: {len(candidates)}")
    return candidates


def should_use_slot_clarification(
    candidates: List[Dict[str, Any]],
    confidence: float,
    clarification_count: int
) -> bool:
    """
    Decide whether to use slot-based clarification.

    Slot clarification is used when:
    - Confidence is low-medium (0.3-0.5) and we have ambiguous candidates
    - We haven't asked too many questions yet

    IMPORTANT: Do NOT use slot clarification for high-confidence direct matches.
    If a user says "water leak on my street", we should ask for location,
    not "how long has this been happening?"

    Args:
        candidates: List of candidate call types
        confidence: Current best confidence score
        clarification_count: Number of clarifications asked so far

    Returns:
        True if should use slot-based clarification
    """
    if not candidates or clarification_count >= 2:
        return False

    # Only use slot clarification for genuinely ambiguous/low confidence cases
    # High confidence (>= 0.7) should proceed directly to location
    if confidence >= 0.7:
        return False

    # Use slot clarification only when confidence is low-medium
    if 0.3 <= confidence < 0.5:
        return True

    # Use when we have multiple very close candidates (truly ambiguous)
    if len(candidates) >= 2 and confidence < 0.6:
        top_conf = candidates[0].get("confidence", 0)
        second_conf = candidates[1].get("confidence", 0)
        if abs(top_conf - second_conf) < 0.1:
            return True

    return False


__all__ = [
    "get_required_slots",
    "get_missing_slots",
    "generate_slot_question",
    "extract_slot_value",
    "filter_candidates_by_slot",
    "should_use_slot_clarification",
    "SLOT_DEFINITIONS",
    "CALL_TYPE_SLOTS",
]
