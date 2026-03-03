"""
Progressive Issue Builder - Smart Context Accumulation
=======================================================

This module handles the intelligent building of issue descriptions across
multiple conversation turns. Instead of just concatenating messages, it:

1. Extracts key information from each user message
2. Merges clarifications with original statements
3. Builds a coherent issue description for classification
4. Generates context-aware follow-up questions that build on previous answers

Key principle: After 2 clarification attempts, classify with whatever we have.
The LLM understands Joburg municipal issues - trust it to find the best match.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from src.conversation.case_memory import CaseMemory

logger = logging.getLogger(__name__)


# Joburg municipal context - the system knows what services exist
JOBURG_MUNICIPAL_SERVICES = {
    "water": ["water supply", "leaks", "burst pipes", "sewage", "drainage", "meters", "pressure"],
    "electricity": ["power outages", "streetlights", "prepaid meters", "cables", "transformers"],
    "roads": ["potholes", "traffic lights", "road signs", "pavements", "bridges", "bollards"],
    "waste": ["refuse collection", "illegal dumping", "bins", "recycling", "dead animals"],
    "transport": ["buses", "bus stops", "routes", "drivers", "Rea Vaya", "MetroBus"],
    "health": ["pests", "noise complaints", "food safety", "pollution"],
    "emergency": ["fire", "accidents", "rescue", "medical emergencies"],
    "billing": ["accounts", "statements", "rates", "payments"],
}


# Context words that help disambiguate issues
CONTEXT_EXTRACTORS = {
    "facility_type": {
        "bus": ["bus", "metrobus", "rea vaya", "public transport"],
        "taxi": ["taxi", "minibus"],
        "clinic": ["clinic", "hospital", "health facility", "medical"],
        "park": ["park", "playground", "recreation", "garden"],
        "station": ["station", "stop", "terminal", "depot"],
        "building": ["building", "office", "library", "community hall"],
        "street": ["street", "road", "pavement", "sidewalk"],
    },
    "issue_type": {
        "dirty": ["dirty", "filthy", "unclean", "messy", "stained", "smelly"],
        "broken": ["broken", "damaged", "not working", "faulty", "out of order"],
        "missing": ["missing", "stolen", "gone", "removed"],
        "blocked": ["blocked", "clogged", "stuck", "jammed"],
        "leaking": ["leaking", "leak", "dripping", "flooding", "water coming out"],
        "no_supply": ["no water", "no power", "no electricity", "nothing coming", "dry"],
    },
    "severity": {
        "urgent": ["urgent", "emergency", "dangerous", "immediately", "asap"],
        "ongoing": ["for days", "for weeks", "long time", "still", "keeps happening"],
    },
}


def extract_context_from_message(message: str) -> Dict[str, str]:
    """
    Extract structured context from a user message.
    Returns dict with extracted aspects like facility_type, issue_type, etc.
    """
    message_lower = message.lower()
    extracted = {}

    for aspect, patterns in CONTEXT_EXTRACTORS.items():
        for label, keywords in patterns.items():
            if any(kw in message_lower for kw in keywords):
                extracted[aspect] = label
                break

    return extracted


def merge_messages_intelligently(messages: List[str]) -> str:
    """
    Merge multiple user messages into a coherent issue description.

    Instead of just concatenating with "|", this:
    1. Removes redundant information
    2. Combines related statements
    3. Creates a natural problem description
    """
    if not messages:
        return ""

    if len(messages) == 1:
        return messages[0]

    # Extract context from all messages
    all_context = {}
    for msg in messages:
        msg_context = extract_context_from_message(msg)
        all_context.update(msg_context)

    # Find the longest/most detailed message as base
    base_message = max(messages, key=len)

    # Add context from other messages that's not in the base
    additions = []
    for msg in messages:
        if msg == base_message:
            continue
        # Check if this message adds new information
        msg_lower = msg.lower()
        base_lower = base_message.lower()
        # Extract words from msg that aren't in base (ignoring common words)
        msg_words = set(msg_lower.split())
        base_words = set(base_lower.split())
        common_words = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that", "i", "my"}
        new_words = msg_words - base_words - common_words
        if new_words:
            # Add only if it adds meaningful context
            meaningful_new = [w for w in new_words if len(w) > 3]
            if meaningful_new:
                additions.append(msg)

    # Build merged description
    if additions:
        # Combine base with additions
        merged = base_message
        for add in additions[:2]:  # Limit to 2 additions to avoid noise
            # Skip if it's very similar to base
            if len(add) > 5 and add.lower() not in base_message.lower():
                merged = f"{merged}. {add}"
        return merged

    return base_message


def build_classification_context(
    memory: CaseMemory,
    current_message: str,
    skip_current: bool = False,
) -> str:
    """
    Build the optimal context string for classification.

    This is smarter than simple concatenation:
    1. Uses cumulative issue if we've been building one
    2. Merges clarification responses with original statement
    3. Weights recent messages but keeps important context

    Args:
        memory: Case memory with conversation history
        current_message: Current user message
        skip_current: If True, exclude current_message from context (e.g. when it's location-only).

    Returns:
        Optimized context string for classification
    """
    if skip_current:
        # Build context from existing messages only; exclude current (e.g. location-only)
        if memory.cumulative_issue:
            return memory.cumulative_issue
        prior = memory.messages[:-1] if memory.messages else []
        recent = prior[-5:] if len(prior) > 5 else prior
        return merge_messages_intelligently(recent) if recent else ""

    # If we have a cumulative issue being built, use that plus current message
    if memory.cumulative_issue:
        # Merge current message with cumulative
        combined = f"{memory.cumulative_issue}. {current_message}"
        memory.update_cumulative_issue(current_message)
        return combined

    # Otherwise, intelligently merge recent messages
    all_messages = memory.messages.copy()
    if current_message not in all_messages:
        all_messages.append(current_message)

    # Use last 5 messages for context
    recent = all_messages[-5:] if len(all_messages) > 5 else all_messages

    # Merge intelligently
    merged = merge_messages_intelligently(recent)

    # Store as cumulative issue for future turns
    memory.update_cumulative_issue(merged)

    return merged


def should_ask_clarification(
    memory: CaseMemory,
    classification_confidence: float,
    has_classification: bool
) -> Tuple[bool, Optional[str]]:
    """
    Decide if we should ask for clarification or just classify.

    Returns:
        (should_ask, reason)
        - should_ask: True if we should ask another question
        - reason: Why we're asking (or why we're not)
    """
    # ESCAPE HATCH: After 2 attempts, classify with whatever we have
    if memory.should_force_classification(max_attempts=2):
        logger.info("Force classification: max clarification attempts reached (%d)", memory.clarification_count)
        return False, "max_attempts_reached"

    # If we have a confident classification, don't ask more
    if has_classification and classification_confidence >= 0.3:
        return False, "confident_classification"

    # If we have no classification at all, we need to ask
    if not has_classification:
        return True, "no_classification"

    # Low confidence but some match - check if we've already asked about this aspect
    if classification_confidence < 0.3:
        # Only ask if we haven't asked this type of question before
        return True, "low_confidence"

    return False, "sufficient_confidence"


def get_next_clarification_aspect(memory: CaseMemory) -> Optional[str]:
    """
    Determine what aspect to ask about next.
    Returns None if we've asked about all relevant aspects.
    """
    # Priority order of aspects to clarify
    aspect_priority = ["facility_type", "issue_type", "severity", "location_type"]

    for aspect in aspect_priority:
        if not memory.is_aspect_clarified(aspect):
            return aspect

    return None


def generate_smart_clarification_question(
    memory: CaseMemory,
    aspect: str,
    detected_category: Optional[str] = None
) -> str:
    """
    Generate a context-aware clarification question that:
    1. Acknowledges what the user already said
    2. Asks about something specific we don't know
    3. Never repeats a question we already asked

    Args:
        memory: Case memory with conversation history
        aspect: The aspect we need to clarify
        detected_category: Service category if detected (water, electricity, etc.)
    """
    last_message = memory.messages[-1] if memory.messages else ""

    # Mark that we're asking about this aspect
    memory.record_asked_question(aspect)
    memory.mark_aspect_clarified(aspect)

    # Generate question based on aspect
    if aspect == "facility_type":
        # Check if they mentioned something but we need more detail
        context = extract_context_from_message(last_message)
        if "issue_type" in context:
            issue = context["issue_type"]
            return f"Got it, you mentioned something is {issue}. Where exactly is this happening - on a bus, at a station, in a park, or somewhere else?"
        return "I understand there's an issue. Can you tell me where this is happening - is it at a public facility, on transport, on the street, or somewhere else?"

    elif aspect == "issue_type":
        return "What exactly is wrong with it? Is it broken, dirty, missing, blocked, or something else?"

    elif aspect == "severity":
        return "How bad is it? Is this urgent, or has it been going on for a while?"

    elif aspect == "location_type":
        return "Is this inside a building, outside on the street, or in a public area?"

    # Fallback
    return "Can you give me a bit more detail about what's happening?"


def detect_municipal_relevance(message: str) -> Tuple[bool, Optional[str]]:
    """
    Check if the message is about a Joburg municipal issue.
    Returns (is_municipal, category)
    """
    message_lower = message.lower()

    for category, keywords in JOBURG_MUNICIPAL_SERVICES.items():
        if any(kw in message_lower for kw in keywords):
            return True, category

    # Check for general municipal indicators
    municipal_indicators = [
        "report", "broken", "not working", "damaged", "leak", "missing",
        "dirty", "blocked", "city", "municipal", "joburg", "johannesburg",
        "council", "public", "street", "road", "service"
    ]

    if any(ind in message_lower for ind in municipal_indicators):
        return True, "general"

    return False, None


__all__ = [
    "build_classification_context",
    "merge_messages_intelligently",
    "extract_context_from_message",
    "should_ask_clarification",
    "get_next_clarification_aspect",
    "generate_smart_clarification_question",
    "detect_municipal_relevance",
    "JOBURG_MUNICIPAL_SERVICES",
]
