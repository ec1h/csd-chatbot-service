"""
Domain/business logic helpers for the CSD Chatbot.

This module contains business logic functions that were extracted from app.py:
- Working memory management
- Location data handling
- Suggested questions generation
- Other domain-specific helpers
"""

from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.database.connection import pg_execute
from src.conversation.conversation_state import ConversationPhase


def init_working_memory() -> Dict[str, Any]:
    """
    Initialize the working memory structure following system instructions.
    This is the EDITABLE MEMORY MODEL that tracks the case being built.

    IMPORTANT: Confidence is EARNED through information collection, not guessed upfront.
    Department resolution happens AFTER problem understanding.
    """
    return {
        # Core case data (editable until locked)
        "intent_bucket": None,
        "department": None,
        "issue_category": None,
        "call_type": None,
        "call_type_code": None,
        "location": None,
        "duration": None,
        "severity": None,
        "confidence": 0.0,
        # NEW: Problem Understanding First (before department)
        "problem_understanding": {
            "raw_description": None,
            "symptoms": [],
            "has_duration": False,
            "has_severity": False,
            "has_location": False,
            "has_confirmation": False,
            "understanding_score": 0.0,
        },
        # NEW: Earned Confidence Tracking
        "confidence_factors": {
            "keyword_match_score": 0.0,
            "symptom_detail_score": 0.0,
            "duration_provided": 0.0,
            "location_provided": 0.0,
            "user_confirmed": 0.0,
            "total_earned": 0.0,
        },
        # NEW: Graceful Degradation State
        "conversation_quality": {
            "consecutive_unclear_inputs": 0,
            "topic_switches_detected": 0,
            "last_understood_topic": None,
            "fallback_mode": False,
            "recovery_attempts": 0,
        },
        # Conversation phase tracking
        "conversation_phase": ConversationPhase.OPEN_INTAKE,
        # Legacy fields for backward compatibility
        "serviceCategory": None,
        "callType": None,
        "callTypeCode": None,
        "issueSummary": None,
        "followUpQuestions": [],
        "callTypeLocked": False,
        "locationRequired": False,
        "awaitingConfirmation": False,
        "conversationHistory": [],
        "awaitingClarification": False,
        "awaitingChangeChoice": False,
        "ready_for_submission": False,
        # AI analysis metadata
        "_ai_extracted_issue": None,
        "_ai_context_type": None,
        "_ai_confidence": None,
        "_matched_keywords": [],
        "_negative_keywords_hit": [],
        "_tentative_matches": [],
        # QA STEP 2: Multi-stage classification tracking
        "_problem_group": None,
        "_classification_stage": 1,
        "_gating_action": None,
        "_gating_reason": None,
        # V5.1: CANONICAL ISSUE FRAME (MANDATORY)
        "issue_frame": {
            "intent_polarity": None,
            "department": None,
            "service_group": None,
            "issue_category": None,
            "issue_type": None,
            "call_type_code": None,
            "confidence": 0.0,
            "locked": False,
            "derived_from": [],
        },
        # V5.1: DECISION TRACE (DEBUG & STABILITY)
        "decision_trace": {
            "semantic_score": 0.0,
            "concept_boosts": [],
            "negative_keyword_hits": [],
            "confidence_weight": 0.0,
            "final_confidence": 0.0,
        },
    }


def get_working_memory(session: Dict[str, Any]) -> Dict[str, Any]:
    """Get or initialize working memory from session"""
    pending = session.get("pending", {})
    if "workingMemory" not in pending:
        return init_working_memory()

    # Get existing memory
    memory = pending.get("workingMemory", {})

    # Ensure all new fields exist (backward compatibility)
    default_memory = init_working_memory()
    for key, default_value in default_memory.items():
        if key not in memory:
            memory[key] = default_value

    return memory


def save_working_memory(session: Dict[str, Any], memory: Dict[str, Any]) -> None:
    """Save working memory to session"""
    pending = session.get("pending", {})
    pending["workingMemory"] = memory
    pg_execute(
        "UPDATE ec1_chat_history SET pending = %s, updated_at = NOW() WHERE session_id = %s",
        (Json(pending), session["_id"]),
    )
    session["pending"] = pending


def set_location_data(session: dict, location: dict) -> None:
    """Store location from external tracker"""
    pending = session.get("pending", {}).copy()
    pending["location"] = {
        "address": location.get("address", ""),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
    }
    pg_execute(
        "UPDATE ec1_chat_history SET pending = %s, updated_at = NOW() WHERE session_id = %s",
        (Json(pending), session["_id"]),
    )
    session["pending"] = pending


def _detect_conversation_domain(
    user_text: str,
    bot_text: str,
    call_type: Optional[str],
    intent_bucket: Optional[str]
) -> Optional[str]:
    """
    Detect the conversation domain (water, electricity, roads, waste, etc.) 
    from all available context to ensure suggestions stay relevant.
    
    Returns domain string or None if domain is not clear yet.
    """
    # Priority 1: Use intent_bucket if already set
    if intent_bucket:
        return intent_bucket
    
    # Priority 2: Detect from call_type string
    if call_type:
        call_type_lower = call_type.lower()
        if any(w in call_type_lower for w in ["water", "pipe", "tap", "sewer", "drainage", "plumbing", "hydrant"]):
            return "water"
        if any(w in call_type_lower for w in ["electric", "power", "light", "outage", "meter", "cable"]):
            return "electricity"
        if any(w in call_type_lower for w in ["road", "pothole", "street", "traffic", "pavement", "sign"]):
            return "roads"
        if any(w in call_type_lower for w in ["waste", "rubbish", "bin", "refuse", "garbage", "trash", "dump"]):
            return "waste"
        if any(w in call_type_lower for w in ["bus", "taxi", "transport", "metrobus", "rea vaya"]):
            return "transport"
        if any(w in call_type_lower for w in ["fire", "emergency", "ems", "medical", "accident"]):
            return "emergency"
    
    # Priority 3: Detect from user's message
    # Water domain keywords
    if any(w in user_text for w in [
        "water", "pipe", "tap", "leak", "burst", "sewer", "sewage", "drain", 
        "drainage", "plumbing", "geyser", "toilet", "flush", "pressure", "hydrant"
    ]):
        return "water"
    
    # Electricity domain keywords
    if any(w in user_text for w in [
        "electric", "power", "light", "electricity", "outage", "blackout", 
        "meter", "cable", "wire", "sparking", "transformer", "streetlight", 
        "street light", "lamp", "volt", "prepaid"
    ]):
        return "electricity"
    
    # Roads domain keywords
    if any(w in user_text for w in [
        "pothole", "road", "street", "pavement", "traffic light", "sign", 
        "highway", "intersection", "crossing", "bridge", "sidewalk", "curb"
    ]):
        return "roads"
    
    # Waste domain keywords
    if any(w in user_text for w in [
        "bin", "rubbish", "refuse", "waste", "garbage", "trash", "dump", 
        "dumping", "pikitup", "collection", "recycling", "litter"
    ]):
        return "waste"
    
    # Transport domain keywords
    if any(w in user_text for w in [
        "bus", "taxi", "metrobus", "rea vaya", "transport", "vehicle", 
        "driver", "route", "schedule", "stop", "station", "seats"
    ]):
        return "transport"
    
    # Emergency domain keywords
    if any(w in user_text for w in [
        "fire", "emergency", "ems", "ambulance", "medical", "accident", 
        "gas leak", "smoke", "flames", "burning"
    ]):
        return "emergency"
    
    # Priority 4: Check bot's response for domain context
    if any(w in bot_text for w in ["water", "pipe", "leak", "sewer", "drain"]):
        return "water"
    if any(w in bot_text for w in ["electric", "power", "light", "outage"]):
        return "electricity"
    if any(w in bot_text for w in ["road", "pothole", "traffic"]):
        return "roads"
    if any(w in bot_text for w in ["bin", "waste", "rubbish", "dump"]):
        return "waste"
    if any(w in bot_text for w in ["bus", "transport", "vehicle"]):
        return "transport"
    
    # No clear domain detected
    return None


def generate_suggested_answers(
    state: Dict[str, Any], 
    last_user_message: Optional[str] = None,
    bot_response: Optional[str] = None,
    current_state: Optional[Any] = None,
    needs_location: bool = False,
) -> List[str]:
    """
    Generate contextual quick-reply answers that the user can tap.
    
    BEHAVIOR CONTRACT COMPLIANCE:
    - Suggestions MUST match conversation state (Rule 10)
    - Suggestions MUST match current domain/topic (Rule 10)
    - NEVER suggest location buttons before issue clarity (Rule 7)
    - NEVER suggest "Water" while resolving electricity issues (Rule 10)
    
    ALWAYS returns helpful options - never returns empty list.
    Context-aware: suggestions stay within the conversation domain (e.g., if talking about water, only suggest water-related options).
    
    Args:
        state: Current conversation state dictionary (working memory)
        last_user_message: Last message from user (for context)
        bot_response: The bot's response (to generate relevant answers)
        current_state: ConversationState enum value
        needs_location: Whether the bot is asking for location
    """
    from src.conversation.conversation_state import ConversationState
    
    phase = state.get("conversation_phase", ConversationPhase.OPEN_INTAKE)
    intent_bucket = state.get("intent_bucket") or state.get("serviceCategory")
    call_type = state.get("call_type") or state.get("callType")
    
    user_text_lower = (last_user_message or "").lower()
    bot_text_lower = (bot_response or "").lower()
    
    # Detect conversation domain from all available context
    detected_domain = _detect_conversation_domain(user_text_lower, bot_text_lower, call_type, intent_bucket)

    # =================================================================
    # STATE-BASED SUGGESTIONS (highest priority)
    # =================================================================
    
    # SUBMITTED - ticket is done (chat is locked)
    if current_state == ConversationState.SUBMITTED or phase == ConversationPhase.LOCKED_FOR_SUBMISSION:
        return []  # Chat is locked, no suggestions needed

    # CONFIRMING - waiting for yes/no
    if current_state == ConversationState.CONFIRMING or state.get("awaitingConfirmation"):
        return ["Yes, that's correct", "No, let me fix something"]

    # NEEDS_LOCATION - we have the issue, asking for location
    if current_state == ConversationState.NEEDS_LOCATION or needs_location:
        return ["Use my current location", "I'll type the address", "It's on a public road"]
    
    # =================================================================
    # BOT QUESTION-BASED SUGGESTIONS
    # =================================================================
    
    # Bot is asking about location/where
    if any(word in bot_text_lower for word in ["where", "location", "address", "drop a pin", "map"]):
        return ["Use my current location", "I'll type the address", "It's on a public road"]
    
    # Bot asked about broken/leaking/missing/damaged - use detected domain
    if any(word in bot_text_lower for word in ["broken", "leaking", "missing", "damaged"]):
        if detected_domain == "water":
            return ["It's leaking water", "It's completely broken", "No water coming out", "The pipe burst"]
        elif detected_domain == "electricity":
            return ["The light is off", "It's flickering", "Cables are damaged", "Multiple lights are out"]
        elif detected_domain == "roads":
            return ["There's a pothole", "Road surface is damaged", "Sign is missing", "Road is flooded"]
        elif detected_domain == "waste":
            return ["Bin is broken", "Bin is missing", "Bin is damaged", "Need replacement"]
        # Generic if no domain detected
        return ["It's broken", "It's leaking", "It's damaged", "It's not working"]
    
    # Bot asked about urgency/severity
    if any(word in bot_text_lower for word in ["urgent", "emergency", "how bad", "serious", "safety"]):
        return ["It's urgent", "It's been like this for days", "It's getting worse", "It's a safety hazard"]
    
    # Bot asked about what's happening/describe - use detected domain for context
    if any(word in bot_text_lower for word in ["what's happening", "what's wrong", "what exactly", "describe", "more detail"]):
        if detected_domain == "water":
            return ["Water is leaking", "No water supply", "Low water pressure", "Sewage problem"]
        elif detected_domain == "electricity":
            return ["No power in area", "Street light out", "Power keeps cutting", "Sparking cables"]
        elif detected_domain == "roads":
            return ["There's a pothole", "Traffic light broken", "Road sign damaged", "Street flooded"]
        elif detected_domain == "waste":
            return ["Bin not collected", "Illegal dumping", "Need a new bin", "Bin overflowing"]
        elif detected_domain == "transport":
            return ["Dirty vehicle", "Bus not running", "Schedule issue", "Driver complaint"]
        # No domain detected yet - provide helpful generic options
        return ["It's broken", "It's leaking", "It's not working", "Tell me more"]
    
    # Bot asked about type/which kind - use detected domain
    if any(word in bot_text_lower for word in ["type", "kind", "which"]):
        if detected_domain == "water":
            return ["Water supply", "Sewage/drainage", "Water meter", "Fire hydrant"]
        elif detected_domain == "electricity":
            return ["Home electricity", "Street lights", "Traffic lights", "Cables/meter"]
        elif detected_domain == "roads":
            return ["Pothole", "Traffic signals", "Road signs", "Road surface"]
        elif detected_domain == "waste":
            return ["Bin collection", "Illegal dumping", "Bin request", "Recycling"]
        elif detected_domain == "transport":
            return ["Bus service", "Rea Vaya", "MetroBus", "Other transport"]
        return ["The first option", "The second option", "Something else"]
    
    # =================================================================
    # USER MESSAGE-BASED SUGGESTIONS (domain-aware)
    # =================================================================
    
    # Special handling for specific issue types within detected domain
    if detected_domain == "transport" and any(w in user_text_lower for w in ["seat", "seats", "dirty", "clean", "filthy"]):
        return ["Bus seats dirty", "Interior needs cleaning", "Multiple seats affected", "Driver complaint"]
    
    if detected_domain == "waste" and any(w in user_text_lower for w in ["dirty", "dump", "filthy"]):
        return ["Illegal dumping", "Area is filthy", "Multiple areas affected", "Health hazard"]
    
    if detected_domain == "water" and any(w in user_text_lower for w in ["dirty", "brown", "smell"]):
        return ["Water is dirty/brown", "Water smells bad", "Water quality issue", "Been like this for days"]
    
    # =================================================================
    # DOMAIN-AWARE DEFAULTS (context matters!)
    # =================================================================
    
    # Domain-specific suggestions to keep conversation focused
    domain_suggestions = {
        "water": ["Burst pipe", "No water", "Low pressure", "Sewer problem"],
        "electricity": ["Power outage", "Street light out", "Sparking cables", "Meter problem"],
        "roads": ["Pothole", "Traffic light broken", "Road flooding", "Sign damaged"],
        "waste": ["Bin not collected", "Illegal dumping", "Need new bin", "Bin overflowing"],
        "transport": ["Dirty vehicle", "Bus not running", "Bus stop damaged", "Schedule issue"],
        "emergency": ["Fire", "Medical emergency", "Gas leak", "Accident"],
    }
    
    # Use detected domain first, then intent bucket
    active_domain = detected_domain or intent_bucket
    
    if active_domain and active_domain in domain_suggestions:
        return domain_suggestions[active_domain]
    
    # OPEN_INTAKE with no domain detected yet - offer broad categories
    if phase == ConversationPhase.OPEN_INTAKE and not detected_domain:
        return ["Water issue", "Electricity problem", "Road issue", "Waste problem"]
    
    # Ultimate fallback - generic helpful options
    return ["Tell me more", "It's urgent", "I need help", "Something else"]


__all__ = [
    "init_working_memory",
    "get_working_memory",
    "save_working_memory",
    "set_location_data",
    "generate_suggested_answers",
]
