"""
Shared helper functions for the CSD Chatbot.

This module centralizes helpers that were previously duplicated across
`orchestrator.py`, `decision_engine.py`, and `app.py`:

- Problem description detection
- Location detection
- Confirmation/rejection detection
- Department/category mapping
"""

from __future__ import annotations

import re
from typing import Optional


# ============================================
# PROBLEM DESCRIPTION DETECTION
# ============================================

def describes_problem(text: str) -> bool:
    """
    Determine if text describes an actual problem vs just a category name.

    This is the canonical implementation of the "Classification Contract"
    previously implemented as `_describes_problem` in `orchestrator.py`.
    """
    if not text:
        return False

    text_lower = text.strip().lower()
    if not text_lower:
        return False

    # Expand contractions for better matching
    expanded = text_lower
    contractions = {
        "there's": "there is",
        "it's": "it is",
        "that's": "that is",
        "what's": "what is",
        "here's": "here is",
        "he's": "he is",
        "she's": "she is",
        "isn't": "is not",
        "aren't": "are not",
        "wasn't": "was not",
        "weren't": "were not",
        "hasn't": "has not",
        "haven't": "have not",
        "hadn't": "had not",
        "doesn't": "does not",
        "don't": "do not",
        "didn't": "did not",
        "can't": "cannot",
        "couldn't": "could not",
        "won't": "will not",
        "wouldn't": "would not",
        "i'm": "i am",
        "we're": "we are",
        "they're": "they are",
        "you're": "you are",
        "i've": "i have",
        "we've": "we have",
        "they've": "they have",
        "you've": "you have",
    }
    for contraction, expansion in contractions.items():
        expanded = expanded.replace(contraction, expansion)

    words = text_lower.split()

    # Single word inputs are likely categories, not problem descriptions
    if len(words) == 1:
        return False

    # Check for action verbs or condition indicators first (these override word count)
    action_indicators = [
        "burst",
        "broken",
        "leak",
        "leaking",
        "flood",
        "flooding",
        "flooded",
        "out",
        "off",
        "not working",
        "damaged",
        "blocked",
        "overflow",
        "overflowing",
        "missing",
        "stolen",
        "stuck",
        "faulty",
        "fault",
        "problem",
        "issue",
        "error",
        "failing",
        "failed",
        "stopped",
        "stopped working",
        "can't",
        "cannot",
        "won't",
        "will not",
        "doesn't",
        "does not",
        "dangerous",
        "pothole",
        "sinkhole",
        "outage",
        "tripping",
        "sparking",
        "smell",
        "smelling",
        "smelly",
        "dirty",
        "brown",
        "discolored",
        # Added more comprehensive problem indicators
        "dumped",
        "dumping",
        "accident",
        "accidents",
        "causing",
        "low pressure",
        "pressure",
        "clogged",
        "rubbish",
        "garbage",
        "trash",
        "waste",
        "fire",
        "smoke",
        "burning",
        "huge",
        "big",
        "large",
        "weeks",
        "days",
        "months",
        "constant",
        "constantly",
        "continuous",
        "continuously",
        "always",
        "never",
        "for days",
        "for weeks",
        "collected",
        "not collected",
        "missed",
        "quality",
    ]

    # Check for common problem patterns (these can match 2-word phrases like "no water")
    # Use the EXPANDED text for pattern matching
    problem_patterns = [
        r"\b(no|not|without)\s+\w+",  # "no water", "not working"
        r"\b\w+\s+(is|are|was|were)\s+\w+",  # "pipe is broken", "lights are off", "there is a"
        r"\b\w+\s+(has|have|had)\s+\w+",  # "pipe has burst", "meter has error"
        r"\b(there|it)\s+(is|are|was|were)\s+",  # "there is a leak", "it is broken"
        r"\b\w+\s+(can't|cannot|won't|will not)\s+\w+",  # "tap can't work"
        r"\bi\s+(need|want|have|am)\s+",  # "i need to report", "i have a problem"
        r"\b(need|want)\s+to\s+(report|fix)",  # "need to report", "want to fix"
        r"\breport(ing)?\s+",  # "reporting a", "report a"
    ]

    has_pattern = any(re.search(pattern, expanded) for pattern in problem_patterns)

    # Check if text contains action/condition indicators
    has_action = any(indicator in text_lower for indicator in action_indicators)

    # For 2-word inputs, require pattern match (e.g., "no water" is OK, but "water pipe" alone is not)
    if len(words) == 2:
        return has_pattern or has_action

    # For 3+ words, accept if has action or pattern
    return has_action or has_pattern


# ============================================
# LOCATION DETECTION
# ============================================

def looks_like_location(text: str) -> bool:
    """
    Determine if text appears to be a location/address.
    
    IMPROVED: Distinguish between problem descriptions that mention roads/streets
    (e.g., "street light is broken") and actual addresses (e.g., "123 Main Street").

    Shared implementation previously known as `_looks_like_location`
    in both `orchestrator.py` and `decision_engine.py`.
    """
    if not text:
        return False

    text_lower = text.strip().lower()

    # Very short or vague locations
    if len(text_lower) < 3:  # Reduced from 5 to allow shorter addresses
        return False
    
    import re
    
    # HIGH CONFIDENCE address patterns - these are definitely locations
    high_confidence_patterns = [
        r'^\d+\s+\w+',  # "123 Main", "45 Oak Avenue"
        r'\w+\s+(street|road|avenue|drive|lane|way|place|crescent|close|court|boulevard|highway)\b',  # "Main Street", "Oak Avenue", "Highway 1"
        r'\b(route|highway|hwy|rd|ave|st|dr)\s*\d+',  # "Route 5", "Highway 1", "Hwy 20"
        r'\bN\d+\b|\bM\d+\b|\bR\d+\b',  # "N1", "M2", "R55" (highway numbers)
        r'corner\s+of\s+\w+',  # "corner of Main"
        r'cnr\s+\w+',  # "cnr Main"
        r'\w+\s+and\s+\w+\s+(street|road|avenue)',  # "Main and Oak Street" (intersection)
        r'ext\s*\d+',  # "ext 5" (extension)
        # STREET ABBREVIATIONS (e.g., "wonder ave", "main rd", "oak st")
        r'\w+\s+(ave|rd|st|dr|blvd|ln|ct|pl)\b',  # "Wonder Ave", "Main Rd", "Oak St"
        r'\w+\s+(ave|rd|st|dr|blvd)\s*,\s*\w+',  # "Wonder Ave, Johannesburg" (with comma)
    ]
    
    # If it matches high-confidence patterns, it's definitely a location
    if any(re.search(p, text_lower) for p in high_confidence_patterns):
        return True

    # IMPORTANT: If text contains problem keywords, it's NOT a pure location
    # This prevents "street light is out on our road" from being treated as a location
    problem_keywords = [
        "broken", "leak", "burst", "blocked", "damaged", "out", "off",
        "not working", "pothole", "sinkhole", "light is", "light not",
        "flooding", "flooded", "fire", "smoke", "accident", "dumping",
        "dirty", "smelly", "overflow", "missing", "stolen", "sparking",
        "outage", "problem", "issue", "fault", "faulty", "no water",
        "no power", "no electricity", "street light", "traffic light",
        "lamp post", "bin", "refuse", "rubbish", "garbage",
        # ADDED: Electrical infrastructure keywords (fix for "electric wires on the road")
        "wires", "wire", "cables", "cable", "electric", "electrical",
        "power line", "power lines", "exposed", "hanging", "down", "fallen"
    ]
    
    if any(kw in text_lower for kw in problem_keywords):
        return False

    # Location indicators - words that commonly appear in addresses
    location_indicators = [
        "street",
        "road",
        "avenue",
        "drive",
        "lane",
        "way",
        "place",
        "crescent",
        "close",
        "court",
        "boulevard",
        "highway",
        "corner",
        "cnr",
        "ext",
        "extension",
    ]

    # Address patterns - more specific location detection
    # Numbers at start (e.g., "123 Main Street")
    starts_with_number = bool(text_lower and text_lower[0].isdigit())
    
    # Contains location indicator as a WHOLE WORD (not a substring).
    # e.g. "drive" must not match inside "driver", "place" must not match inside "placement".
    has_location_word = any(
        re.search(r"\b" + re.escape(ind) + r"\b", text_lower)
        for ind in location_indicators
    )
    
    # Additional patterns that suggest addresses
    address_patterns = [
        r'\w+\s+and\s+\w+',  # "Main and Oak" (intersection)
    ]
    
    has_address_pattern = any(re.search(p, text_lower) for p in address_patterns)
    
    return starts_with_number or has_location_word or has_address_pattern


# ============================================
# CONFIRMATION/REJECTION DETECTION
# ============================================

CONFIRMATION_WORDS = [
    "yes",
    "correct",
    "confirm",
    "confirmed",
    "that's right",
    "that's correct",
    "thats correct",
    "thats right",
    "yep",
    "yeah",
    "yup",
    "ok",
    "okay",
    "sure",
    "absolutely",
    "affirmative",
    # NEW: Additional natural language confirmations (Behavior Contract Rule 8)
    "looks good",
    "that looks right",
    "all good",
    "sounds good",
    "sounds right",
    "i think so",
    "i guess so",
    "probably",
    "right",
]

REJECTION_WORDS = {"no", "nope", "incorrect", "wrong", "not right", "change"}


def is_confirmation(text: str, conversation_history: list = None) -> bool:
    """
    Check if text is a confirmation response.
    
    Uses SEMANTIC INTENT detection, not just keywords.
    Fast keyword check first, then LLM for semantic understanding.
    
    CRITICAL: Humans don't always say "yes" - they might say:
    - "good"
    - "looks right"
    - "that's it"
    - "exactly"
    """
    if not text:
        return False
    text_lower = text.strip().lower()

    # FAST PATH: Exact keyword match (performance optimization)
    if text_lower in CONFIRMATION_WORDS:
        return True

    # Check if starts with confirmation word (handles "yes, that's correct", "yes please", etc.)
    for word in CONFIRMATION_WORDS:
        # Match word followed by space, comma, period, or exclamation
        if text_lower.startswith(word + " ") or text_lower.startswith(word + ",") or \
           text_lower.startswith(word + ".") or text_lower.startswith(word + "!"):
            return True

    # Check if contains key confirmation phrases
    confirmation_phrases = ["that's correct", "thats correct", "that is correct", "is correct"]
    if any(phrase in text_lower for phrase in confirmation_phrases):
        return True

    # SEMANTIC PATH: Use LLM for intent detection (handles "good", "looks right", etc.)
    if conversation_history:
        try:
            from src.conversation.intent_detector import detect_confirmation_intent
            intent = detect_confirmation_intent(text, conversation_history)
            if intent == "AFFIRM":
                return True
        except Exception:
            pass  # Fall back to False if LLM fails
    
    return False


def is_rejection(text: str, conversation_history: list = None) -> bool:
    """
    Check if text is a rejection/cancellation/correction response.
    
    Uses SEMANTIC INTENT detection, not just keywords.
    Fast keyword check first, then LLM for semantic understanding.
    
    CRITICAL: Humans don't always say "no" - they might say:
    - "not that"
    - "nah"
    - "eish no"
    - "something else"
    - "you got it wrong"
    - "wait"
    - "hold on"
    
    Returns True for DENY, CORRECT, or UNSURE intents.
    """
    if not text:
        return False
    text_lower = text.strip().lower()
    
    # FAST PATH: Exact keyword match (performance optimization)
    if text_lower in REJECTION_WORDS or any(
        text_lower.startswith(word + " ") for word in REJECTION_WORDS
    ):
        return True
    
    # Normalize apostrophes first (handles smart quotes and regular quotes)
    normalized_text = text_lower.replace("'", "'").replace("'", "'").replace("'", "'")
    
    # Natural language rejection phrases (check both original and normalized)
    rejection_phrases = [
        "can i change",
        "can i fix",
        "can i update",
        "can i correct",
        "can i modify",
        "let me change",
        "let me fix",
        "let me update",
        "let me correct",
        "let me modify",
        "i want to change",
        "i want to fix",
        "i want to update",
        "i want to correct",
        "i want to modify",
        "i need to change",
        "i need to fix",
        "i need to update",
        "i need to correct",
        "i need to modify",
        "need to change",
        "need to fix",
        "need to update",
        "want to change",
        "want to fix",
        "want to update",
        "not correct",
        "not right",
        "that's wrong",
        "thats wrong",
        "that is wrong",
        "it's wrong",
        "its wrong",
        "it is wrong",
        "that's not right",
        "thats not right",
        "that is not right",
        "it's not right",
        "its not right",
        "it is not right",
        # NEW: Additional natural denial phrases
        "not that",
        "nah",
        "something else",
        "you got it wrong",
        "that's not what i",
        "thats not what i",
    ]
    
    # Check phrases against both original and normalized text
    for phrase in rejection_phrases:
        if phrase in text_lower or phrase in normalized_text:
            return True
    
    # SEMANTIC PATH: Use LLM for intent detection
    # Catches: "eish no", "hold on", "wait", "not quite", etc.
    if conversation_history:
        try:
            from src.conversation.intent_detector import detect_confirmation_intent
            intent = detect_confirmation_intent(text, conversation_history)
            # DENY, CORRECT, or UNSURE all count as rejection
            if intent in ["DENY", "CORRECT", "UNSURE"]:
                return True
        except Exception:
            pass  # Fall back to False if LLM fails
    
    return False


# ============================================
# DEPARTMENT MAPPING (SINGLE SOURCE OF TRUTH)
# ============================================

DEPARTMENT_MAPPING = {
    "water": "Water and Sanitation",
    "electricity": "City Power",
    "waste": "Pikitup",
    "roads": "Johannesburg Roads Agency",
    "transport": "Transportation",
    "fire": "Emergency Services",
    "ems": "Emergency Medical Services",
    "environmental": "Environmental Health",
    "revenue": "Revenue and Customer Relations",
    "housing": "Housing",
    "parks": "City Parks and Zoo",
}


def get_department_name(category: str) -> Optional[str]:
    """Get department name for a category."""
    if not category:
        return None
    return DEPARTMENT_MAPPING.get(category.lower())


def get_category_for_department(department: str) -> Optional[str]:
    """Reverse lookup: get category for department name."""
    if not department:
        return None
    department_lower = department.lower()
    for cat, dept in DEPARTMENT_MAPPING.items():
        if dept.lower() == department_lower:
            return cat
    return None


__all__ = [
    "describes_problem",
    "looks_like_location",
    "is_confirmation",
    "is_rejection",
    "DEPARTMENT_MAPPING",
    "get_department_name",
    "get_category_for_department",
]

