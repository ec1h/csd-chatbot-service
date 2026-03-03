"""
Response Generator - Human-Readable Responses Only
===================================================
This generates human-readable responses based on state and memory.
Rules:
- No AI logic
- No thresholds
- No classification calls
- Responses should be warm, empathetic, and human
- Sound like a helpful neighbor, not a customer service bot
"""

import random
import re
import logging
from typing import Optional, Dict, Any
from src.conversation.conversation_state import ConversationState
from src.conversation.case_memory import CaseMemory
from src.utils.helpers import describes_problem

logger = logging.getLogger(__name__)


# =============================================================================
# GREETING RESPONSES - Friendly and welcoming
# =============================================================================
GREETING_RESPONSES = [
    "Hey there! What's going on?",
    "Hi! How can I help you today?",
    "Hello! What seems to be the problem?",
]


# =============================================================================
# CLARIFICATION RESPONSES - Context-aware, acknowledge what user said
# =============================================================================

# For vague single words like "water", "electricity", "roads"
CATEGORY_ONLY_RESPONSES = {
    "water": [
        "Water issue — got it. What's actually happening? Is it a leak, no water, bad pressure, or something else?",
        "Okay, water problem. Can you tell me what's going on? Like a burst pipe, no water coming out, or dirty water?",
        "Water — sure. What exactly is the problem you're seeing?",
    ],
    "electricity": [
        "Electricity issue — okay. What's happening? Power out completely, flickering lights, sparking wires?",
        "Got it, electricity. Can you describe what's wrong? No power, faulty streetlight, or something else?",
        "Okay, power problem. What exactly are you experiencing?",
    ],
    "roads": [
        "Road issue — got it. What's the problem? Pothole, damaged sign, flooding, or something else?",
        "Okay, roads. What are you seeing? A pothole, broken traffic light, or roadwork issue?",
        "Sure, road problem. Can you tell me what's happening?",
    ],
    "waste": [
        "Waste issue — okay. Is it missed collection, illegal dumping, or overflowing bins?",
        "Got it, waste. What's going on? Bins not collected, rubbish piling up?",
        "Okay, waste problem. What exactly is happening?",
    ],
    "general": [
        "Okay, I hear you. Tell me what's going wrong so I can get the right team on it.",
        "Thanks for flagging this. What exactly is happening – what are you seeing?",
        "I'm listening. What's going wrong with it – for example, how bad is it or what exactly are you seeing?",
    ],
}

# For short/vague messages that don't give enough detail
# These should give helpful examples to guide the user
SHORT_MESSAGE_RESPONSES = [
    "I want to help, but I need more details. Is this about water, electricity, roads, or something else? What's happening?",
    "Could you tell me more? For example: 'There's a water leak on my street' or 'No power in my area'.",
    "What's going on? Give me some details like what's broken, leaking, or not working.",
]

# For messages that mention a category but are still vague
VAGUE_PROBLEM_RESPONSES = [
    "I hear you. Can you tell me exactly what's happening? For example, is something leaking, broken, or blocked?",
    "Got it. What specifically is the problem — is it leaking, not working, overflowing, or damaged?",
    "Sure. Can you describe what you're seeing? That way I can send the right team.",
]


# =============================================================================
# REJECTION RESPONSES - When user says "no" to confirmation
# =============================================================================
REJECTION_RESPONSES = [
    "No problem! Just tell me the correct issue or location and I'll update it.",
    "Okay! Please provide the correct details — either describe the issue again or give me the right location.",
    "Got it! What should I change? You can describe the issue differently or provide a new location.",
]


# =============================================================================
# LOCATION REQUEST - After we know the issue
# Use the classified issue type, not raw user words
# =============================================================================
LOCATION_REQUEST_RESPONSES = [
    "Got it — {issue}.",
    "I understand there's a {issue}.",
    "Understood — {issue}.",
]

LOCATION_REQUEST_GENERIC = [
    "Got it.",
    "Understood.",
]


# =============================================================================
# CONFIRMATION - Before submitting (BEHAVIOR CONTRACT RULE 8)
# Natural language confirmation - accepts "yes", "looks good", "i think so", etc.
# =============================================================================
CONFIRMATION_RESPONSES = [
    "Alright, just to confirm: {issue} at {location}. Is that correct?",
    "Got it — {issue} at {location}. Does that look right?",
    "So that's {issue} at {location}. All good?",
    "Let me confirm: {issue} at {location}. Sound right?",
]

# High-confidence confirmations (when we're very sure)
CONFIRMATION_HIGH_CONFIDENCE = [
    "Got it — {issue} at {location}. Ready to submit?",
    "Understood: {issue} at {location}. Should I log this?",
]


# =============================================================================
# SUBMISSION - After confirmation (Final goodbye - chat is locked)
# =============================================================================
SUBMISSION_RESPONSES = [
    "Done! Your report is logged and the team will handle it. Thanks for letting us know.\n\nIf you need to report a new issue, please start a new chat.",
    "All sorted! We've got your report. Thanks for reporting this.\n\nTo report another issue, please open a new chat.",
    "Submitted! Help is on the way. Thanks for being proactive.\n\nIf you have a different issue to report, please start a new chat.",
]


def _display_issue(raw: str) -> str:
    """Convert a raw call-type label into a natural display phrase.

    Examples
    --------
    "PROBLEM PASSENGERS"        → "problem with passengers"
    "BUS NON-ARRIVAL"           → "bus non-arrival"
    "NO WATER SUPPLY"           → "no water supply"
    "DRIVER BEHAVIOUR"          → "driver behaviour"
    "DAMAGED BUS STOP"          → "damaged bus stop"
    """
    text = raw.strip().lower()

    # Patterns that produce broken English when used with "there's a {issue}"
    # e.g. "problem passengers" → "problem with passengers"
    text = re.sub(r"^problem\s+(?!with\b)", "problem with ", text)

    # "non-arrival" → keep as-is; already readable
    return text


def _format_slot_options(memory: CaseMemory) -> str:
    """
    Format human-friendly options for missing slots stored in memory.

    This keeps the *what to ask* decision inside the system while giving
    the user clear, contextual choices.
    """
    if not memory.missing_slots or not memory.clarification_options:
        return ""

    lines = []
    # For now we only expect a single slot like "facility_type", but this
    # works with multiple slots as well.
    for slot in memory.missing_slots:
        options = memory.clarification_options.get(slot) or []
        if not options:
            continue
        # Simple bullet list; frontend will render as plain text.
        for opt in options:
            lines.append(f"- {opt}")

    return "\n".join(lines)


def _detect_category_from_message(text: str) -> str:
    """Detect if user mentioned a service category."""
    text_lower = text.lower()

    if any(w in text_lower for w in ["water", "pipe", "tap", "sewage", "sewer", "drain"]):
        return "water"
    if any(w in text_lower for w in ["electric", "power", "light", "outage", "meter"]):
        return "electricity"
    if any(w in text_lower for w in ["road", "pothole", "street", "traffic", "sign"]):
        return "roads"
    if any(w in text_lower for w in ["waste", "rubbish", "bin", "garbage", "trash", "dump"]):
        return "waste"
    return "general"


def _generate_contextual_clarification(memory: CaseMemory) -> str:
    """
    Generate a clarifying question that acknowledges what the user said.
    Uses rule-based logic for context-aware responses.

    IMPROVED: Checks conversation history to avoid repeating questions
    and generates progressive follow-ups that build on previous answers.
    """
    last_message = memory.messages[-1] if memory.messages else ""
    category = _detect_category_from_message(last_message)

    # Check if this is just a category word
    stripped = last_message.strip().lower()
    if stripped in ["water", "electricity", "roads", "waste", "power", "electric"]:
        responses = CATEGORY_ONLY_RESPONSES.get(category, CATEGORY_ONLY_RESPONSES["general"])
        return random.choice(responses)

    # IMPROVED: Check FULL conversation for context, not just last message
    full_context = " ".join(memory.messages).lower() if memory.messages else stripped

    # Special handling for cleanliness of seats / vehicles / public areas
    # e.g. "the seats are dirty", "bus is filthy inside"
    if any(word in full_context for word in ["seat", "seats", "bench", "benches"]) and any(
        word in full_context for word in ["dirty", "filthy", "unclean", "messy", "smelly", "stained"]
    ):
        # Check if user has ALREADY provided context anywhere in conversation
        context_words = [
            "bus", "taxi", "minibus", "clinic", "hospital", "park",
            "playground", "station", "stop", "waiting area", "public building",
        ]
        has_context = any(ctx_word in full_context for ctx_word in context_words)

        if has_context:
            # User told us where (e.g., "bus seats are dirty")
            # DON'T prematurely say "let me log this" - we still need classification to succeed
            # If we're here in ISSUE_BUILDING, it means classification didn't reach 0.3 confidence
            # Ask for any additional details that might help classification
            if not memory.was_question_asked("severity"):
                memory.record_asked_question("severity")
                followups = [
                    "Got it, dirty seats on the bus. Is this one bus or have you noticed it on multiple buses?",
                    "Okay, so the seats are dirty. Is this a specific bus or have you seen this on multiple buses?",
                ]
                return random.choice(followups)
            elif not memory.was_question_asked("details"):
                memory.record_asked_question("details")
                followups = [
                    "Thanks. Can you tell me which bus route or where you saw this?",
                    "Okay. Is there anything else relevant to this issue?",
                ]
                return random.choice(followups)
            else:
                # We've asked enough - this fallback should rarely happen
                # The escape hatch in clarification.py should force classification before this
                return "Thanks for reporting. Can you confirm this is about dirty bus seats so I can log it properly?"

        # Check if we already asked about facility type (avoid repeating)
        if memory.was_question_asked("facility_type"):
            # We already asked - try a different approach
            return "I want to make sure I understand. Can you describe the area where you saw this issue?"

        # First time asking
        seat_clarifications = [
            "Got it, the seating is dirty. Is this inside a bus, at a bus stop, or in another public area?",
            "Okay, so the seats are dirty. Are you talking about a bus, a waiting area, or somewhere else?",
        ]
        memory.record_asked_question("facility_type")
        return random.choice(seat_clarifications)

    # Check if message is very short (1-3 words)
    word_count = len(stripped.split())
    if word_count <= 3:
        # If the user has ALREADY described a problem earlier in the conversation,
        # don't act as if they haven't told us anything. Ask for NEXT details instead.
        prior_messages = memory.messages[:-1] if len(memory.messages) > 1 else []
        prior_has_problem = any(describes_problem(m) for m in prior_messages)
        if prior_has_problem:
            # Check what we've already asked about
            if not memory.was_question_asked("severity"):
                memory.record_asked_question("severity")
                followups = [
                    "Got it. How bad is it - is this urgent or has it been going on for a while?",
                    "Understood. Is this a new issue or has it been happening for some time?",
                ]
                return random.choice(followups)
            elif not memory.was_question_asked("details"):
                memory.record_asked_question("details")
                followups = [
                    "Thanks. Any other details I should know about?",
                    "Okay. Is there anything else relevant to this issue?",
                ]
                return random.choice(followups)
            else:
                # We've asked enough - proceed with classification
                return "Thanks for the details. Let me process this for you."
        return random.choice(SHORT_MESSAGE_RESPONSES)

    # For longer but still vague messages, use rule-based clarification
    # Fallback to category-aware response
    responses = CATEGORY_ONLY_RESPONSES.get(category, CATEGORY_ONLY_RESPONSES["general"])
    return random.choice(responses)


def generate_response(state: ConversationState, memory: CaseMemory) -> str:
    """
    Generate a human-readable response based on state and memory.

    Responses are warm, natural, and conversational — like talking to a helpful neighbor.
    """
    if state == ConversationState.OPEN:
        return random.choice(GREETING_RESPONSES)

    if state == ConversationState.ISSUE_BUILDING:
        # Check if we're coming from a rejection (user said "no" to confirmation)
        if memory.location and memory.issue_summary:
            return random.choice(REJECTION_RESPONSES)

        # Generate context-aware clarification
        return _generate_contextual_clarification(memory)

    if state == ConversationState.AWAITING_CLARIFICATION:
        # Progressive clarification: we already know the gist of the issue,
        # but we need one or two key details before we can safely classify.
        base_issue = memory.last_intent_summary or (
            memory.messages[-1] if memory.messages else "the issue"
        )
        base_issue = base_issue.strip()
        if base_issue and not base_issue.endswith("."):
            base_issue = base_issue[0].upper() + base_issue[1:]

        slot_text = _format_slot_options(memory)

        if slot_text:
            return (
                f"I want to make sure I understand properly.\n"
                f"{base_issue} — where are these seats exactly?\n\n"
                f"Are the seats:\n{slot_text}\n\n"
                f"You can just pick the one that fits best or describe it in your own words."
            )

        # Fallback if, for some reason, we don't have structured options.
        return _generate_contextual_clarification(memory)

    if state == ConversationState.NEEDS_LOCATION:
        if memory.issue_summary:
            issue_text = _display_issue(memory.issue_summary)
            template = random.choice(LOCATION_REQUEST_RESPONSES)
            return template.format(issue=issue_text)
        return random.choice(LOCATION_REQUEST_GENERIC)

    if state == ConversationState.CONFIRMING:
        issue_display = _display_issue(memory.issue_summary) if memory.issue_summary else "the issue"
        location_display = memory.location

        # Guard: if location is not yet collected, ask for it instead of
        # rendering a broken "at the location" confirmation string.
        if not location_display:
            if memory.issue_summary:
                issue_text = _display_issue(memory.issue_summary)
                template = random.choice(LOCATION_REQUEST_RESPONSES)
                return template.format(issue=issue_text)
            return random.choice(LOCATION_REQUEST_GENERIC)

        # We have both issue and location — render the confirmation.
        if (memory.last_classification_method == "direct_match" and
                memory.last_classification_confidence >= 0.85):
            template = random.choice(CONFIRMATION_HIGH_CONFIDENCE)
        else:
            template = random.choice(CONFIRMATION_RESPONSES)
        return template.format(issue=issue_display, location=location_display)

    if state == ConversationState.SUBMITTED:
        return random.choice(SUBMISSION_RESPONSES)

    # Fallback
    return "What's happening? Tell me more so I can help."

# NEW: Generate response structure with selected call type
def generate_response_structure(state: ConversationState, memory: CaseMemory) -> Dict[str, Any]:
    """
    Generate the complete response structure including selected call type.
    """
    response = generate_response(state, memory)
    
    # Get frontend flags including selected call type
    from .frontend_signals import get_frontend_flags
    frontend_flags = get_frontend_flags(state, memory)
    
    # Include selected call type in the response structure
    selected_calltype = memory.selected_call_type if memory.selected_call_type else None
    
    return {
        "response": response,
        "state": state.name,
        "memory": {
            "issue_summary": memory.issue_summary,
            "call_type_code": memory.call_type_code,
            "location": memory.location,
            "selected_calltype": selected_calltype
        },
        "frontend_flags": frontend_flags
    }