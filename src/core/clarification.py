"""
Clarification Helper - Progressive Case Building
================================================

This module decides WHEN we must pause classification and ask the user
for targeted clarification, and HOW we track that missing information.

Key principles:
- This module NEVER calls classifiers or returns call types.
- It only reasons about "slots" of information that are still missing.
- The system decides *what* is missing; the LLM later decides *how* to
  phrase the clarifying question (in `response_generator`).

IMPORTANT: ESCAPE HATCH
After 2 clarification attempts, we FORCE classification with whatever context
we have. This prevents infinite loops where the bot keeps asking the same
question.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from src.conversation.conversation_state import ConversationState
from src.conversation.case_memory import CaseMemory
from src.core.intent_extraction import IntentExtractionResult


logger = logging.getLogger(__name__)

# Maximum clarification attempts before forcing classification (legacy slot-based)
MAX_CLARIFICATION_ATTEMPTS = 2

# Simplified flow: max classification misses before "we don't understand" + LLM question
MAX_CLASSIFICATION_MISSES = 3


class ClarificationDecision(BaseModel):
    """
    Structured decision about whether clarification is required.
    """

    clarification_required: bool = Field(
        ...,
        description="True if we should pause classification and ask a clarifying question.",
    )
    missing_slots: List[str] = Field(
        default_factory=list,
        description="Semantic slots that are not yet filled (e.g. 'facility_type').",
    )
    slot_options: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="For each missing slot, a small set of human-meaningful options.",
    )
    intent_summary: Optional[str] = Field(
        default=None,
        description="Short summary of the issue from the intent extractor.",
    )
    force_classify: bool = Field(
        default=False,
        description="True if we should skip clarification and force classification.",
    )
    skip_reason: Optional[str] = Field(
        default=None,
        description="Reason why clarification was skipped.",
    )


def decide_clarification(
    intent: IntentExtractionResult,
    current_state: ConversationState,
    memory: CaseMemory,
) -> ClarificationDecision:
    """
    Decide if we must **block classification** and ask a targeted
    clarifying question instead.

    Design constraints:
    - Only ever *adds* behaviour on top of existing flow.
    - ESCAPE HATCH: After 2 clarification attempts, force classification.
    - Check if user's response already contains the context we need.
    """
    # Only consider early conversational states
    if current_state not in {ConversationState.OPEN, ConversationState.ISSUE_BUILDING}:
        return ClarificationDecision(clarification_required=False)

    # If we already have a call type on record, defer to existing flow
    if memory.call_type_code is not None:
        return ClarificationDecision(clarification_required=False)

    # ESCAPE HATCH: If we've already asked for clarification twice, stop asking
    # and force classification with whatever context we have
    if memory.should_force_classification(max_attempts=MAX_CLARIFICATION_ATTEMPTS):
        logger.info(
            "ESCAPE HATCH: Max clarification attempts (%d) reached. Forcing classification.",
            memory.clarification_count,
        )
        return ClarificationDecision(
            clarification_required=False,
            force_classify=True,
            skip_reason="max_attempts_reached",
        )

    issue_l = (intent.issue_summary or "").lower()

    # Check if we have ambiguous patterns that need clarification
    # This is more generic than just seats - handles any ambiguous issue
    ambiguous_patterns = _detect_ambiguous_patterns(issue_l, memory)

    if not ambiguous_patterns:
        return ClarificationDecision(clarification_required=False)

    if not intent.missing_slots:
        return ClarificationDecision(clarification_required=False)

    if intent.confidence >= 0.8:
        # High-confidence understanding – let classifier behave as before.
        return ClarificationDecision(clarification_required=False)

    # Check if user already provided context in their message
    # If so, mark those aspects as clarified and don't ask again
    _extract_and_mark_provided_context(issue_l, memory)

    # Map missing slots to concrete options (only for slots not yet clarified)
    slot_options: Dict[str, List[str]] = {}
    remaining_slots = []

    for slot in intent.missing_slots:
        # Skip if we already asked about this or if user already provided it
        if memory.is_aspect_clarified(slot):
            continue
        if memory.was_question_asked(slot):
            # We already asked - don't ask again
            continue

        options = _get_slot_options(slot, issue_l)
        if options:
            slot_options[slot] = options
            remaining_slots.append(slot)

    # If no actionable slots remain, don't block classification
    if not remaining_slots:
        logger.info("All slots already clarified or asked about, proceeding to classification")
        return ClarificationDecision(
            clarification_required=False,
            skip_reason="all_slots_addressed",
        )

    # Increment clarification counter
    memory.increment_clarification()

    logger.info(
        "Progressive clarification engaged; missing_slots=%s, attempt=%d/%d",
        remaining_slots,
        memory.clarification_count,
        MAX_CLARIFICATION_ATTEMPTS,
    )

    return ClarificationDecision(
        clarification_required=True,
        missing_slots=remaining_slots,
        slot_options=slot_options,
        intent_summary=intent.issue_summary,
    )


def _detect_ambiguous_patterns(issue_text: str, memory: CaseMemory) -> bool:
    """
    Detect if the issue text contains ambiguous patterns that need clarification.
    More generic than just seats - handles various ambiguous scenarios.
    """
    # Patterns that are ambiguous without additional context
    ambiguous_keywords = {
        # Seating/benches - could be bus, park, clinic, etc.
        "seat": True,
        "seats": True,
        "bench": True,
        "benches": True,
        # Generic cleanliness - need to know what/where
        "dirty": True,
        "filthy": True,
        "unclean": True,
        # Generic infrastructure - need specifics
        "broken": True,
        "damaged": True,
        "not working": True,
    }

    # Context words that resolve ambiguity (if present, no clarification needed)
    context_resolvers = [
        "bus", "taxi", "clinic", "hospital", "park", "playground",
        "station", "stop", "building", "office", "street", "road",
        "water", "electricity", "power", "pipe", "meter", "light",
    ]

    has_ambiguous = any(kw in issue_text for kw in ambiguous_keywords)
    has_context = any(ctx in issue_text for ctx in context_resolvers)

    # If we have ambiguous keywords but already have context, no need to clarify
    if has_ambiguous and has_context:
        return False

    # Only return True if truly ambiguous (has ambiguous word, no context)
    return has_ambiguous and not has_context


def _extract_and_mark_provided_context(issue_text: str, memory: CaseMemory) -> None:
    """
    Extract context that the user already provided and mark it as clarified.
    This prevents asking about things the user already told us.
    """
    # Facility type detection
    facility_keywords = {
        "bus": "facility_type",
        "taxi": "facility_type",
        "clinic": "facility_type",
        "hospital": "facility_type",
        "park": "facility_type",
        "station": "facility_type",
        "stop": "facility_type",
        "building": "facility_type",
    }

    for keyword, aspect in facility_keywords.items():
        if keyword in issue_text:
            memory.mark_aspect_clarified(aspect)
            break

    # Location type detection
    location_keywords = {
        "inside": "location_type",
        "outside": "location_type",
        "on the street": "location_type",
        "in the road": "location_type",
    }

    for keyword, aspect in location_keywords.items():
        if keyword in issue_text:
            memory.mark_aspect_clarified(aspect)
            break


def _get_slot_options(slot: str, issue_text: str) -> List[str]:
    """
    Get options for a specific slot, customized based on context.
    """
    if slot == "facility_type":
        # Check if it's about seating
        if any(word in issue_text for word in ["seat", "seats", "bench", "benches"]):
            return [
                "on a bus or taxi",
                "in a clinic or hospital",
                "in a park",
                "at a bus stop or station",
                "inside a public building",
            ]
        # Generic facility options
        return [
            "on public transport (bus/taxi)",
            "in a public building",
            "on the street/road",
            "in a park or outdoor area",
        ]

    if slot == "location_type":
        return [
            "inside a vehicle",
            "at a station or stop",
            "inside a public facility",
            "in an outdoor public area",
        ]

    if slot == "issue_type":
        return [
            "dirty or unclean",
            "broken or damaged",
            "missing or stolen",
            "blocked or clogged",
        ]

    return []


def apply_clarification_plan_to_memory(
    decision: ClarificationDecision,
    memory: CaseMemory,
) -> None:
    """
    Persist the clarification plan into CaseMemory so that:
    - Response generation can phrase the right question
    - Subsequent turns can know which slots are still missing
    """
    if not decision.clarification_required:
        return

    # Track which slots we're asking about
    memory.missing_slots = list(decision.missing_slots)
    memory.clarification_options = dict(decision.slot_options)
    memory.last_intent_summary = decision.intent_summary or memory.issue_summary

    # Record that we asked about these slots (to avoid repeating)
    for slot in decision.missing_slots:
        memory.record_asked_question(slot)


def fill_missing_slots_from_reply(user_text: str, memory: CaseMemory) -> None:
    """
    Fill missing slots from the user's reply to a clarifying question.

    IMPROVED: Actually extracts context from the reply and marks it as clarified,
    preventing the same question from being asked again.
    """
    if not user_text or not user_text.strip():
        return

    if not memory.missing_slots:
        return

    user_lower = user_text.lower()

    # Extract context from the reply
    _extract_and_mark_provided_context(user_lower, memory)

    # Update cumulative issue with the clarification
    memory.update_cumulative_issue(user_text)

    logger.info(
        "Processed user clarification reply. Slots addressed, clarified_aspects=%s",
        memory.clarified_aspects,
    )

    # Clear the missing slots - user has responded
    memory.missing_slots = []
    memory.clarification_options = {}


def _category_from_context(text: str) -> str:
    """Simple category hint from context for LLM clarification."""
    t = (text or "").lower()
    if any(w in t for w in ["water", "pipe", "tap", "sewage", "sewer", "drain", "leak"]):
        return "water"
    if any(w in t for w in ["electric", "power", "light", "outage", "meter", "street light"]):
        return "electricity"
    if any(w in t for w in ["road", "pothole", "street", "traffic", "sign", "pavement"]):
        return "roads"
    if any(w in t for w in ["waste", "rubbish", "bin", "garbage", "dump", "refuse"]):
        return "waste"
    return "general"


def _asks_for_location(text: str) -> bool:
    """True if the question asks for location/address – we must not do that before we have a call type."""
    t = (text or "").lower()
    return any(
        phrase in t
        for phrase in [
            "location", "address", "street", "where is", "where exactly", "where are",
            "drop a pin", "on the map", "nearest landmark", "which street", "which area",
        ]
    )


def generate_simple_clarification_question(memory: CaseMemory) -> str:
    """
    Ask a helpful clarifying question based on context.
    Called when we have no call type hit yet and miss_count < max.
    Never ask for location – we ask that only after we have a call type.

    Phase 5: Enhanced to prevent asking same question twice.
    Phase 6: Better acknowledgment of what user said.
    """
    context = memory.get_full_context() or " ".join(memory.messages) if memory.messages else ""
    context_lower = context.lower()
    last_msg = memory.messages[-1].lower() if memory.messages else ""

    # If no context at all, ask for the problem
    if not context.strip():
        return "Hi there! What issue would you like to report?"

    # Build acknowledgment prefix based on what user said
    ack_prefix = ""
    if last_msg and len(last_msg) > 5:
        # Short acknowledgment of what they said
        if "problem" in last_msg or "issue" in last_msg:
            ack_prefix = "I see there's an issue. "
        elif any(w in last_msg for w in ["broken", "damaged", "not working"]):
            ack_prefix = "Got it, something's broken. "
        elif any(w in last_msg for w in ["leak", "leaking"]):
            ack_prefix = "I understand there's a leak. "
        elif any(w in last_msg for w in ["dirty", "filthy", "unclean"]):
            ack_prefix = "Got it, something needs cleaning. "
    
    # Generate context-specific questions based on detected keywords
    # Phase 5: Track question categories to avoid repeating
    # Phase 6: Use ack_prefix to acknowledge what user said

    # Water-related
    if any(w in context_lower for w in ["water", "pipe", "tap", "leak", "burst", "sewer", "drain"]):
        if not memory.was_question_asked("water_clarification"):
            memory.record_asked_question("water_clarification")
            if "leak" in context_lower:
                return ack_prefix + "Is this inside your property or on the street? How bad is it?"
            if "no water" in context_lower or "dry" in context_lower:
                return ack_prefix + "Are your neighbours also affected, or just your property?"
            if "sewer" in context_lower or "drain" in context_lower:
                return ack_prefix + "Is it overflowing or just blocked? On your property or the street?"
            return ack_prefix + "Is this a leak, no water, blocked drain, or something else?"

    # Electricity-related
    if any(w in context_lower for w in ["electric", "power", "light", "outage", "spark", "cable"]):
        if not memory.was_question_asked("electricity_clarification"):
            memory.record_asked_question("electricity_clarification")
            if "street light" in context_lower or "lamp" in context_lower:
                return ack_prefix + "Is it one street light or multiple in the area?"
            if "no power" in context_lower or "outage" in context_lower:
                return ack_prefix + "Is it just your home or the whole street/area?"
            if "spark" in context_lower or "cable" in context_lower:
                return ack_prefix + "Are sparks coming from cables or a pole? Is it safe there?"
            return ack_prefix + "Is this about no power, street lights, or cables?"

    # Road-related
    if any(w in context_lower for w in ["road", "pothole", "traffic", "street", "sign", "sinkhole"]):
        if not memory.was_question_asked("road_clarification"):
            memory.record_asked_question("road_clarification")
            if "pothole" in context_lower:
                return ack_prefix + "How big is the pothole roughly? Is it causing problems?"
            if "traffic light" in context_lower or "robot" in context_lower:
                return ack_prefix + "Is it completely off, flashing, or stuck on one colour?"
            return ack_prefix + "Is this a pothole, traffic light, road sign, or flooding?"

    # Waste-related
    if any(w in context_lower for w in ["bin", "refuse", "rubbish", "garbage", "dump", "waste", "collect"]):
        if not memory.was_question_asked("waste_clarification"):
            memory.record_asked_question("waste_clarification")
            if "not collected" in context_lower or "missed" in context_lower:
                return ack_prefix + "When was it last collected? Just your bin or the whole street?"
            if "dump" in context_lower:
                return ack_prefix + "What kind of rubbish is being dumped and roughly how much?"
            return ack_prefix + "Is this missed collection, illegal dumping, or need a new bin?"

    # Driver behavior issues (MUST check BEFORE generic bus/vehicle checks)
    if any(w in context_lower for w in ["driver", "driving"]):
        if any(w in context_lower for w in ["misbehav", "rude", "aggressive", "bad", "reckless", "dangerous", "inappropriate", "unprofessional"]):
            if not memory.was_question_asked("driver_behavior_clarification"):
                memory.record_asked_question("driver_behavior_clarification")
                return ack_prefix + "What is the driver doing? (e.g., driving recklessly, being rude, refusing service)"
    
    # Dirty/cleaning related (ONLY if actual cleanliness words present)
    has_cleanliness_word = any(w in context_lower for w in ["dirty", "clean", "filthy", "unclean", "messy", "stain", "smell"])
    has_location_word = any(w in context_lower for w in ["seat", "bus", "vehicle", "taxi", "building", "area"])
    
    if has_cleanliness_word and has_location_word:
        if not memory.was_question_asked("cleanliness_clarification"):
            memory.record_asked_question("cleanliness_clarification")
            return ack_prefix + "Is this a bus/taxi, public building, or outdoor area?"
    
    # Try LLM for anything else
    try:
        from src.core.dspy_pipeline import clarifying_question_generator
        category = _category_from_context(context)
        out = clarifying_question_generator(user_message=context, service_category=category)
        q = (getattr(out, "clarifying_question", None) or "").strip()
        if q and not _asks_for_location(q):
            return ack_prefix + q if ack_prefix else q
    except Exception as e:
        logger.warning("LLM clarification failed: %s", e)

    # Generic but helpful fallback with acknowledgment
    if ack_prefix:
        return ack_prefix + "Can you tell me more specifically what's happening?"
    return "Could you tell me what's happening? Is something broken, leaking, or not working?"


def generate_we_dont_understand_question(memory: CaseMemory) -> str:
    """
    Honest message after multiple classification misses.
    Be helpful by giving examples of what we CAN help with.
    Never ask for location.
    """
    context = memory.get_full_context() or " ".join(memory.messages) if memory.messages else ""
    context_lower = context.lower()
    
    # Build a helpful response based on what we think they might need
    prefix = "I'm not quite sure what type of service this needs. "
    
    # Check if any category keywords are present
    if any(w in context_lower for w in ["water", "pipe", "tap", "sewer"]):
        return prefix + "Is this about a water leak, no water supply, or a sewer/drainage issue? Please tell me what's happening with the water."
    
    if any(w in context_lower for w in ["electric", "power", "light"]):
        return prefix + "Is this about a power outage, street lights, or electrical cables? Please describe what's wrong with the electricity."
    
    if any(w in context_lower for w in ["road", "street", "traffic"]):
        return prefix + "Is this about potholes, traffic lights, road signs, or road flooding? Please describe the road issue."
    
    if any(w in context_lower for w in ["bin", "refuse", "rubbish", "waste"]):
        return prefix + "Is this about missed refuse collection, illegal dumping, or needing a new bin? Please describe the waste issue."
    
    # Generic helpful response with examples
    return (
        "I'm having trouble understanding what you need help with. "
        "I can help with things like:\n"
        "• Water issues (leaks, no water, sewer problems)\n"
        "• Electricity (power outages, street lights)\n"
        "• Roads (potholes, traffic lights, flooding)\n"
        "• Waste (refuse collection, illegal dumping)\n\n"
        "Which of these is closest to your issue?"
    )


__all__ = [
    "ClarificationDecision",
    "decide_clarification",
    "apply_clarification_plan_to_memory",
    "fill_missing_slots_from_reply",
    "MAX_CLARIFICATION_ATTEMPTS",
    "MAX_CLASSIFICATION_MISSES",
    "generate_simple_clarification_question",
    "generate_we_dont_understand_question",
]

