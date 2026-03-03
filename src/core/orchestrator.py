"""
Orchestrator - The Only Glue Layer
===================================
This is the ONLY place where layers connect.
Flow:
1. Append user message to memory
2. Run SMART classifier (pattern match → keyword/semantic → LLM)
3. Decide next state
4. Generate response
5. Generate frontend flags

IMPROVED clarification:
- Smart classifier tries multiple techniques before giving up
- Direct pattern matching catches 90% of clear problem descriptions
- LLM assists when keywords/semantics fail
- Force progression: NEVER get stuck in ISSUE_BUILDING if user describes a problem
"""

import difflib  # For fuzzy string matching (typo detection)

from src.conversation.conversation_state import ConversationState
from src.conversation.case_memory import CaseMemory
from src.classification.classifier_service import classify_issue
from src.classification.smart_classifier import smart_classify, direct_pattern_match
from src.conversation.decision_engine import decide_next_state
from src.conversation.response_generator import generate_response
from src.conversation.frontend_signals import get_frontend_flags
from src.conversation.intent_detector import should_handle_as_navigation
from src.core.issue_normalizer import normalize_issue_description  # For "no i meant X" extraction
from src.conversation.domain_detector import (
    is_domain_only_input,
    detect_domain,
    generate_domain_clarification,
)
from src.utils.helpers import (
    describes_problem,
    looks_like_location,
    is_confirmation,
    is_rejection,
)

from src.utils.data_loader import get_fallback_general_call_type
from src.core.clarification import (
    generate_simple_clarification_question,
    generate_we_dont_understand_question,
)
from src.core.progressive_issue_builder import build_classification_context
from src.core.issue_normalizer import normalize_issue_description, normalize_with_clarifications
from src.core.slot_clarification import (
    should_use_slot_clarification,
    get_missing_slots,
    generate_slot_question,
)
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# NEW BEHAVIOR CONTRACT: Confidence-Guided Progression
# Low confidence (< 0.4): Ask clarifying questions
# Medium confidence (0.4-0.7): Confirm understanding before proceeding
# High confidence (>= 0.7): Proceed directly to location request

CONFIDENCE_THRESHOLD_LOW = 0.4    # Below this: need clarification
CONFIDENCE_THRESHOLD_MEDIUM = 0.7  # Below this: confirm before proceeding
CONFIDENCE_THRESHOLD_HIGH = 0.7    # At or above: high confidence, proceed

# For direct pattern matches and first turns
CONFIDENCE_FIRST_TURN_THRESHOLD = 0.25  # Lower for first turn with clear problem
CONFIDENCE_DIRECT_MATCH_THRESHOLD = 0.50  # Direct pattern matches trusted

# Max clarification questions limit (HARD RULE)
MAX_CLARIFICATION_QUESTIONS = 3


def process_user_message(
    user_text: str,
    current_state: ConversationState,
    memory: CaseMemory,
    external_location: Optional[str] = None
) -> Dict[str, Any]:
    # NEW: Store selected call type description in memory immediately
    if memory.call_type_code and not memory.issue_summary:
        # Try to get issue summary from existing call type
        from src.classification.call_type_matcher import get_call_type_description
        memory.issue_summary = get_call_type_description(memory.call_type_code)
    """
    Process a user message through the complete flow.
    
    This is the ONLY place where layers connect.
    
    Args:
        user_text: The user's message
        current_state: Current conversation state
        memory: Current case memory
        external_location: Optional location from external GPS/map picker
    
    Returns:
    {
        "response": str,
        "state": ConversationState,
        "memory": CaseMemory,
        "frontend_flags": Dict[str, bool]
    }
    """
    # STEP 1: Handle external location if provided
    if external_location:
        memory.update_location(external_location)
    
    # STEP 2: Append user message to memory
    memory.append_message(user_text)
    
    state_for_logic = current_state
    logger.info(f"ORCHESTRATOR START: state={current_state.name if hasattr(current_state, 'name') else current_state}, has_call_type={bool(memory.call_type_code)}, input='{user_text[:50]}'")

# =========================================================================
# GLOBAL NAVIGATION CHECK - Simple intent detection for ambiguous cases
# This handles cases like "i want my pipe to change" vs "change the issue"
# Only runs for AMBIGUOUS cases - doesn't interfere with existing logic
# CRITICAL: Skip when in CONFIRMING state - let the SMART SHORTCUTS handle rejection
# =========================================================================
    logger.info(f"DEBUG: current_state={current_state}, checking if should skip global nav (skip if CONFIRMING)")
    if current_state != ConversationState.CONFIRMING:
        logger.info(f"DEBUG: Not in CONFIRMING, checking global navigation")
        try:
            if should_handle_as_navigation(user_text, memory.messages):
                logger.info(f"Navigation intent detected - handling as navigation")
                # Reset to fresh state and ask what they want to do
                memory.reset_clarification_state()
                memory.in_correction_mode = True
                classification = {
                    "issue_label": memory.issue_summary,
                    "call_type_code": memory.call_type_code,
                    "confidence": 1.0 if memory.call_type_code else 0.0,
                }
                next_state = ConversationState.ISSUE_BUILDING
                response = "No problem! What would you like to do? You can describe a new issue or tell me what to change."
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        except Exception as e:
            # If intent detection fails, continue with existing logic
            logger.warning(f"Intent detection failed, using existing logic: {e}")

    # STEP 3: NEEDS_LOCATION – accept location only, never re-classify
    if current_state == ConversationState.NEEDS_LOCATION and not external_location:
        logger.info(f"In NEEDS_LOCATION state - checking if input is location")
        
        # Check for rejection with new issue (e.g., "no i meant power outage")
        if is_rejection(user_text, conversation_history=memory.messages):
            import re
            correction_patterns = [
                r"no\s+(?:i\s+)?meant\s+(.+)",
                r"no\s+it'?s\s+(.+)",
                r"no\s+actually\s+(.+)",
                r"no\s+the\s+(?:issue|problem)\s+is\s+(.+)",
            ]
            
            user_text_lower = user_text.lower()
            extracted_issue = None
            for pattern in correction_patterns:
                match = re.match(pattern, user_text_lower, re.IGNORECASE)
                if match:
                    extracted_issue = match.group(1).strip()
                    if len(extracted_issue.split()) >= 2:
                        logger.info(f"NEEDS_LOCATION: Rejection with new issue: '{extracted_issue}'")
                        break
                    else:
                        extracted_issue = None
            
            if extracted_issue:
                # Reclassify with new issue
                memory.reset_clarification_state()
                memory.issue_summary = None
                memory.call_type_code = None
                memory.location = None
                
                normalized_extracted = normalize_issue_description(extracted_issue, memory)
                classification = smart_classify(
                    text=normalized_extracted,
                    conversation_history=memory.messages,
                    existing_classification=None
                )
                
                if classification.get("call_type_code") and classification.get("confidence", 0) >= 0.4:
                    memory.issue_summary = classification["issue_label"]
                    memory.call_type_code = classification["call_type_code"]
                    next_state = ConversationState.NEEDS_LOCATION
                    response = generate_response(next_state, memory)
                    frontend_flags = get_frontend_flags(next_state)
                    return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        if looks_like_location(user_text):
            logger.info(f"Accepted location: {user_text[:50]}")
            memory.update_location(user_text)
        classification = {
            "issue_label": memory.issue_summary,
            "call_type_code": memory.call_type_code,
            "confidence": 1.0,
        }
        next_state = decide_next_state(current_state, classification, memory, user_text)
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # =========================================================================
    # BEHAVIOR CONTRACT RULE 9: Rejection & Correction Flow (Smart Shortcuts)
    # STEP 4: CONFIRMING – handle yes/no with smart shortcuts
    # =========================================================================
    if current_state == ConversationState.CONFIRMING:
        if is_confirmation(user_text, conversation_history=memory.messages):
            memory.confirm()
            classification = {
                "issue_label": memory.issue_summary,
                "call_type_code": memory.call_type_code,
                "confidence": 1.0,
            }
            next_state = decide_next_state(current_state, classification, memory, user_text)
            response = generate_response(next_state, memory)
            frontend_flags = get_frontend_flags(next_state)
            return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        elif is_rejection(user_text, conversation_history=memory.messages):
            # User rejected confirmation - check for smart shortcuts
            user_text_lower = user_text.lower()
            
            # SMART SHORTCUT 0: User provides new issue in rejection (e.g., "no i meant pothole on the road")
            # Patterns: "no i meant X", "no it's X", "no actually X", "no the issue is X"
            import re
            correction_patterns = [
                r"no\s+(?:i\s+)?meant\s+(.+)",
                r"no\s+it'?s\s+(.+)",
                r"no\s+actually\s+(.+)",
                r"no\s+the\s+(?:issue|problem)\s+is\s+(.+)",
                r"no\s+(?:it'?s|this\s+is)\s+(?:a|an)?\s*(.+)",
            ]
            
            extracted_issue = None
            for pattern in correction_patterns:
                match = re.match(pattern, user_text_lower, re.IGNORECASE)
                if match:
                    extracted_issue = match.group(1).strip()
                    # Check if extracted text is substantial (not just "issue" or "problem")
                    if len(extracted_issue.split()) >= 2 or extracted_issue not in ["issue", "problem", "location"]:
                        logger.info(f"Rejection with issue provided: '{extracted_issue}'")
                        break
                    else:
                        extracted_issue = None
            
            # If we extracted a real issue, reclassify immediately
            logger.info(f"DEBUG: extracted_issue={extracted_issue}, checking SMART SHORTCUTS")
            if extracted_issue:
                # Reset and reclassify with the new issue
                memory.reset_clarification_state()
                memory.issue_summary = None
                memory.call_type_code = None
                memory.location = None  # Also reset location since issue changed
                memory.in_correction_mode = True
                
                # Reclassify with the extracted issue
                logger.info(f"Reclassifying with extracted issue: '{extracted_issue}'")
                
                # Normalize and classify the extracted issue
                normalized_extracted = normalize_issue_description(extracted_issue, memory)
                
                classification = smart_classify(
                    text=normalized_extracted,
                    conversation_history=memory.messages,
                    existing_classification=None
                )
                
                # If we got a good classification, proceed to location
                if classification.get("call_type_code") and classification.get("confidence", 0) >= 0.4:
                    memory.issue_summary = classification["issue_label"]
                    memory.call_type_code = classification["call_type_code"]
                    next_state = ConversationState.NEEDS_LOCATION
                    response = generate_response(next_state, memory)
                    frontend_flags = get_frontend_flags(next_state)
                    return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
                else:
                    # Couldn't classify with confidence - ask for more details
                    classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
                    next_state = ConversationState.ISSUE_BUILDING
                    response = f"I understand you meant '{extracted_issue}'. Can you tell me more about this issue?"
                    frontend_flags = get_frontend_flags(next_state)
                    return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
            
            # Smart Shortcut 1: User says "location" - ask for location immediately
            elif "location" in user_text_lower and "issue" not in user_text_lower:
                logger.info(f"SMART SHORTCUT 1 FIRED: User wants to change location - '{user_text[:50]}'")
                memory.location = None  # Reset location
                memory.in_correction_mode = False
                classification = {
                    "issue_label": memory.issue_summary,
                    "call_type_code": memory.call_type_code,
                    "confidence": 1.0,
                }
                next_state = ConversationState.NEEDS_LOCATION
                response = generate_response(next_state, memory)
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
            
            # Smart Shortcut 2: User says "issue" - re-enter issue clarification
            elif "issue" in user_text_lower or "problem" in user_text_lower:
                memory.reset_clarification_state()
                memory.issue_summary = None
                memory.call_type_code = None
                memory.in_correction_mode = True
                classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
                next_state = ConversationState.ISSUE_BUILDING
                response = "No problem! Please describe the issue again."
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
            
            # Smart Shortcut 3: User says "both" - reset both issue + location
            elif "both" in user_text_lower:
                memory.reset_clarification_state()
                memory.issue_summary = None
                memory.call_type_code = None
                memory.location = None
                memory.in_correction_mode = True
                classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
                next_state = ConversationState.ISSUE_BUILDING
                response = "No problem! Let's start over. What's the issue you want to report?"
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
            
            # Default: Ask what to change
            else:
                memory.reset_clarification_state()
                memory.in_correction_mode = True
                classification = {
                    "issue_label": memory.issue_summary,
                    "call_type_code": memory.call_type_code,
                    "confidence": 1.0,
                }
                next_state = ConversationState.ISSUE_BUILDING
                response = "No problem! What would you like to change — the issue or the location?"
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Neither confirmation nor rejection - stay in confirming
        classification = {
            "issue_label": memory.issue_summary,
            "call_type_code": memory.call_type_code,
            "confidence": 1.0,
        }
        next_state = current_state
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # STEP 5: SUBMITTED – chat is locked, reject new messages
    if current_state == ConversationState.SUBMITTED:
        classification = {"issue_label": memory.issue_summary, "call_type_code": memory.call_type_code, "confidence": 1.0}
        # Generate a response reminding the user that this chat is locked
        response = "This report has been submitted and the chat is now closed. Please start a new chat to report a different issue."
        frontend_flags = get_frontend_flags(current_state)
        return {"response": response, "state": current_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # STEP 6: CORRECTION MODE – Handle corrections after rejection
    if memory.in_correction_mode and state_for_logic == ConversationState.ISSUE_BUILDING:
        # User rejected confirmation and is providing corrections
        logger.info("In correction mode - analyzing user input for corrections")
        
        # CRITICAL FIX: Check for navigation keywords FIRST before treating as descriptions
        # Words like "issue", "the issue", "location", "the location" are navigation, not content
        user_text_lower = user_text.lower().strip()
        user_text_clean = user_text_lower.replace("the ", "").replace("my ", "").replace("a ", "").strip()
        is_short_input = len(user_text.split()) <= 3
        
        # Navigation keyword: "issue" or "the issue" (not a full description)
        if is_short_input and user_text_clean in ["issue", "problem", "issue please", "problem please"]:
            logger.info(f"Navigation keyword detected: '{user_text}' - asking for issue description")
            response = "No problem! Please describe the issue again."
            memory.reset_clarification_state()
            memory.issue_summary = None
            memory.call_type_code = None
            classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
            next_state = ConversationState.ISSUE_BUILDING
            frontend_flags = get_frontend_flags(next_state)
            return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Navigation keyword: "location" or "the location" (not an actual location)
        if is_short_input and user_text_clean in ["location", "address", "location please", "address please"]:
            logger.info(f"Navigation keyword detected: '{user_text}' - asking for location")
            memory.location = None
            classification = {
                "issue_label": memory.issue_summary,
                "call_type_code": memory.call_type_code,
                "confidence": 1.0,
            }
            next_state = ConversationState.NEEDS_LOCATION
            response = generate_response(next_state, memory)
            frontend_flags = get_frontend_flags(next_state)
            return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # ROBUST FIX: Detect navigation phrases (handles typos and variations)
        # Strategy: In correction mode, if user mentions "issue"/"location" WITHOUT actual problem details,
        # it's almost certainly navigation, not a new problem description
        
        # Fuzzy match helper function
        def fuzzy_match_word(text: str, target: str, threshold: float = 0.70) -> tuple:
            """Check if any word in text is similar to target word. Returns (matched, word, similarity)"""
            words = text.split()
            for word in words:
                if len(word) >= max(3, len(target) - 3) and len(word) <= len(target) + 3:
                    similarity = difflib.SequenceMatcher(None, word, target).ratio()
                    if similarity >= threshold:
                        return (True, word, similarity)
            return (False, None, 0.0)
        
        # Check for "issue" or "problem" (with fuzzy matching for typos)
        issue_ref = "issue" in user_text_lower or "problem" in user_text_lower
        if not issue_ref:
            # Try fuzzy matching for typos like "isseu", "isue", "problm", "probem"
            match_issue = fuzzy_match_word(user_text_lower, "issue", 0.70)
            match_problem = fuzzy_match_word(user_text_lower, "problem", 0.70)
            if match_issue[0]:
                issue_ref = True
                logger.info(f"Fuzzy matched '{match_issue[1]}' to 'issue' (similarity: {match_issue[2]:.2f})")
            elif match_problem[0]:
                issue_ref = True
                logger.info(f"Fuzzy matched '{match_problem[1]}' to 'problem' (similarity: {match_problem[2]:.2f})")
        
        # Check for "location", "address", or "place" (with fuzzy matching for typos)
        location_ref = "location" in user_text_lower or "address" in user_text_lower or "place" in user_text_lower
        if not location_ref:
            # Try fuzzy matching for typos like "locaton", "loction", "adress", "addres"
            match_location = fuzzy_match_word(user_text_lower, "location", 0.70)
            match_address = fuzzy_match_word(user_text_lower, "address", 0.70)
            match_place = fuzzy_match_word(user_text_lower, "place", 0.75)
            if match_location[0]:
                location_ref = True
                logger.info(f"Fuzzy matched '{match_location[1]}' to 'location' (similarity: {match_location[2]:.2f})")
            elif match_address[0]:
                location_ref = True
                logger.info(f"Fuzzy matched '{match_address[1]}' to 'address' (similarity: {match_address[2]:.2f})")
            elif match_place[0]:
                location_ref = True
                logger.info(f"Fuzzy matched '{match_place[1]}' to 'place' (similarity: {match_place[2]:.2f})")
        
        # Question patterns that indicate navigation (handles "can i", "should i", etc.)
        question_words = ["can i", "could i", "should i", "may i", "would", "shall i"]
        has_question_pattern = any(q in user_text_lower for q in question_words)
        
        # Change/action intent indicators (with robust fuzzy matching for typos)
        # Multiple patterns to catch various typos: change, chamge, chnage, chang, changd, etc.
        change_indicators = [
            "chang",    # catches: change, chamge, chnage, changing, etc.
            "chng",     # catches: chng, chnge, etc.
            "fix",      # catches: fix, fixing, etc.
            "correct",  # catches: correct, correction, etc.
            "update",   
            "modify",
            "adjust",
            "edit",
            "redo",
            "undo"
        ]
        # Also check for edit distance: if a word is 1-2 chars different from "change", likely a typo
        words_in_text = user_text_lower.split()
        has_change_intent = any(ind in user_text_lower for ind in change_indicators)
        
        # Fuzzy match for "change" with typos (e.g., "changd", "chage", "cahnge")
        if not has_change_intent:
            for word in words_in_text:
                if len(word) >= 4 and len(word) <= 8:  # "change" is 6 chars, allow 4-8
                    similarity = difflib.SequenceMatcher(None, word, "change").ratio()
                    if similarity >= 0.70:  # 70% similar to "change"
                        has_change_intent = True
                        logger.info(f"Fuzzy matched '{word}' to 'change' (similarity: {similarity:.2f})")
                        break
        
        # Meta words indicating intent
        meta_words = ["want", "need", "like", "prefer", "wanna", "gonna"]
        has_meta_word = any(word in user_text_lower for word in meta_words)
        
        # Actual problem description indicators (these suggest it's a real problem, not navigation)
        problem_words = ["burst", "broken", "leak", "leaking", "flood", "flooding", "overflow", "blocked", 
                         "damaged", "missing", "stolen", "stuck", "faulty", "not working", "doesn't work",
                         "cracked", "pothole", "collapsed"]
        has_real_problem = any(word in user_text_lower for word in problem_words)
        
        # DECISION LOGIC: Is this navigation or a new problem description?
        # Navigation if:
        # 1. Mentions "issue/problem" + (has change intent OR question pattern OR meta word) + NO real problem words
        # 2. It's relatively short (not a detailed description) - under 15 words
        word_count = len(user_text.split())
        is_short_phrase = word_count < 15
        
        # Issue change navigation detection
        if issue_ref and is_short_phrase and not has_real_problem:
            # Any of these patterns indicates navigation:
            if has_change_intent or has_question_pattern or has_meta_word:
                logger.info(f"Navigation detected (issue): '{user_text}' [change:{has_change_intent}, question:{has_question_pattern}, meta:{has_meta_word}]")
                response = "No problem! Please describe the issue again."
                memory.reset_clarification_state()
                memory.issue_summary = None
                memory.call_type_code = None
                classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
                next_state = ConversationState.ISSUE_BUILDING
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Location change navigation detection
        if location_ref and is_short_phrase and not looks_like_location(user_text):
            if has_change_intent or has_question_pattern or has_meta_word:
                logger.info(f"Navigation detected (location): '{user_text}' [change:{has_change_intent}, question:{has_question_pattern}, meta:{has_meta_word}]")
                memory.location = None
                classification = {
                    "issue_label": memory.issue_summary,
                    "call_type_code": memory.call_type_code,
                    "confidence": 1.0,
                }
                next_state = ConversationState.NEEDS_LOCATION
                response = generate_response(next_state, memory)
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Check if user is providing a new location (keep issue, update location)
        if looks_like_location(user_text) and not describes_problem(user_text):
            logger.info(f"Detected location correction: {user_text}")
            memory.update_location(user_text)
            memory.in_correction_mode = False  # Done correcting
            classification = {
                "issue_label": memory.issue_summary,
                "call_type_code": memory.call_type_code,
                "confidence": 1.0,
            }
            next_state = ConversationState.CONFIRMING  # Go back to confirmation
            response = generate_response(next_state, memory)
            frontend_flags = get_frontend_flags(next_state)
            return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Check if user is providing a new issue description (keep location, update issue)
        elif describes_problem(user_text):
            logger.info(f"Detected issue correction: {user_text}")
            # Reclassify the new issue description
            direct_match = direct_pattern_match(user_text)
            if direct_match and direct_match.confidence >= 0.80:
                classification = {
                    "issue_label": direct_match.issue_label,
                    "call_type_code": direct_match.call_type_code,
                    "confidence": direct_match.confidence,
                }
            else:
                normalized_text = normalize_issue_description(user_text, memory)
                classification_context = _build_classification_context(memory, normalized_text, skip_current=False)
                classification = classify_issue(text=classification_context, conversation_history=memory.messages)
            
            # Update issue if we got a good classification
            if classification.get("call_type_code"):
                memory.update_issue(
                    issue_summary=classification.get("issue_label"),
                    call_type_code=classification.get("call_type_code")
                )
                memory.in_correction_mode = False  # Done correcting
                next_state = ConversationState.CONFIRMING  # Go back to confirmation
                response = generate_response(next_state, memory)
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # If we can't determine what they're correcting, ask for clarification
        memory.in_correction_mode = False  # Exit correction mode, continue with normal flow
        logger.info("Could not determine correction intent - continuing with normal flow")
    
    # =========================================================================
    # BEHAVIOR CONTRACT RULE 1: Greeting & Entry Behavior (Hard Rule)
    # Greetings must NEVER trigger classification and MUST stay in OPEN state
    # =========================================================================
    if state_for_logic == ConversationState.OPEN and _is_greeting_only(user_text):
        logger.info("Greeting detected - staying in OPEN state, no classification")
        classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0, "candidates": []}
        next_state = ConversationState.OPEN  # MUST stay in OPEN
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
    
    # =========================================================================
    # BEHAVIOR CONTRACT RULE 2: Domains ≠ Issues (Progressive Intent Rule)
    # Single words like "electricity", "power", "water" are domains, not issues
    # They require clarification before classification
    # =========================================================================
    if state_for_logic in {ConversationState.OPEN, ConversationState.ISSUE_BUILDING}:
        # Check if input is domain-only (single word like "power", "water")
        if is_domain_only_input(user_text):
            detected_domain = detect_domain(user_text)
            logger.info(f"Domain-only input detected: {detected_domain}")
            
            # Update memory with detected domain
            memory.update_domain(detected_domain)
            
            # Generate clarification question for the domain
            if detected_domain:
                response = generate_domain_clarification(detected_domain)
            else:
                response = "I want to help, but I need more details. What exactly is happening?"
            
            classification = {
                "issue_label": None,
                "call_type_code": None,
                "confidence": 0.0,
                "candidates": [],
                "intent_bucket": detected_domain
            }
            next_state = ConversationState.ISSUE_BUILDING
            frontend_flags = get_frontend_flags(next_state)
            return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
    
    # STEP 7: OPEN / ISSUE_BUILDING – SMART classification with multiple techniques

    # Location is collected exclusively via the frontend popup (body.location).
    # Never extract location from message text.
    skip_current = False

    # If message doesn't describe a problem and it's the first turn, ask for more info
    if state_for_logic == ConversationState.OPEN and not describes_problem(user_text) and len(memory.messages) <= 1:
        classification = {"issue_label": None, "call_type_code": None, "confidence": 0.0}
        next_state = ConversationState.ISSUE_BUILDING
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # =====================================================
    # SMART CLASSIFICATION: Try multiple techniques
    # =====================================================
    
    # Step 1: Try direct pattern matching FIRST on ORIGINAL text (fastest, most reliable)
    # IMPORTANT: Check this BEFORE normalization, as LLM may rephrase and lose exact keywords
    direct_match = direct_pattern_match(user_text)
    
    # If we have a high-confidence direct match, use it immediately
    # This prevents the normalization layer from rephrasing away exact pattern matches
    if direct_match and direct_match.confidence >= 0.80:
        logger.info(f"Using direct pattern match before normalization: {direct_match.issue_label} (conf={direct_match.confidence})")
        # Convert ClassificationResult to dict format for compatibility
        classification = {
            "issue_label": direct_match.issue_label,
            "call_type_code": direct_match.call_type_code,
            "confidence": direct_match.confidence,
            "_smart_method": direct_match.method,
            "_matched_pattern": direct_match.matched_pattern
        }
        # IMPORTANT: Reset retry counters on successful match
        # Apply the classification hit which resets clarification counters
        _apply_classification_hit(memory, classification)
        
        # Determine next state and return
        next_state = decide_next_state(state_for_logic, classification, memory, user_text)
        if next_state == ConversationState.NEEDS_LOCATION and memory.location:
            next_state = ConversationState.CONFIRMING
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
    else:
        # Step 2: VAGUENESS CHECK (CRITICAL - must happen BEFORE normalization)
        # DO NOT normalize vague inputs - they need clarification first
        # The normalizer would expand "electricity issues" into a specific description
        # which would then bypass vagueness detection in smart_classify
        from src.classification.smart_classifier import is_too_vague
        
        if is_too_vague(user_text):
            logger.info(f"ORCHESTRATOR: Input is too vague - skipping normalization: '{user_text[:50]}...'")
            classification = {
                "issue_label": None,
                "call_type_code": None,
                "confidence": 0.15,  # Very low to force clarification
                "_vague_input": True
            }
        else:
            # Step 3: NORMALIZE user text before classification (Phase 2 - Normalization Layer)
            # This transforms raw user input into a canonical issue description
            # Fallback: if normalization fails, returns original user_text (safe degradation)
            #
            # Phase 3: Smart clarification handling
            # If we're answering a clarification question, merge the answer with previous context
            is_answering_clarification = (
                state_for_logic == ConversationState.ISSUE_BUILDING and 
                memory.clarification_count > 0 and 
                len(memory.messages) > 1
            )
            
            if is_answering_clarification:
                # Use enhanced normalization that merges clarification answers with original context
                logger.info("Processing clarification answer - using enhanced normalization")
                normalized_text = normalize_with_clarifications(user_text, memory)
            else:
                # Standard normalization for initial problem description
                normalized_text = normalize_issue_description(user_text, memory)
            
            # Step 4: Build context and run keyword/semantic classifier
            # Now using normalized_text instead of raw user_text for better classification
            classification_context = _build_classification_context(memory, normalized_text, skip_current=skip_current)
            keyword_classification = classify_issue(text=classification_context, conversation_history=memory.messages, top_n=10)
            memory.last_classification_confidence = keyword_classification.get("confidence", 0.0)
            
            # =====================================================================
            # BEHAVIOR CONTRACT: Store Top-N Candidates (Critical for Discoverability)
            # All call types remain "alive" through candidates - rare types emerge naturally
            # =====================================================================
            candidates = keyword_classification.get("candidates", [])
            if candidates:
                memory.store_candidates(candidates)
                logger.info(f"Stored {len(candidates)} candidates for progressive clarification")
            
            # Detect and track domain
            detected_domain = keyword_classification.get("intent_bucket")
            if detected_domain:
                # =====================================================================
                # BEHAVIOR CONTRACT RULE 4: Topic Switching & Contradictions
                # Detect when user changes topics and pivot gracefully
                # =====================================================================
                if memory.detect_domain_change(detected_domain):
                    logger.info(f"Topic switch detected: {memory.last_detected_domain} -> {detected_domain}")
                    # Clear previous context on topic switch
                    memory.reset_clarification_state()
                
                memory.update_domain(detected_domain)
            
            # Step 5: Use smart_classify to combine all signals
            # Using normalized_text for consistency with classification context
            classification = smart_classify(
                text=normalized_text,
                conversation_history=memory.messages,
                existing_classification=keyword_classification
            )
    
    # =========================================================================
    # BEHAVIOR CONTRACT RULE 6: Confidence-Guided Progression
    # Low (< 0.4): Ask clarifying questions
    # Medium (0.4-0.7): Confirm understanding
    # High (>= 0.7): Proceed to location
    # =========================================================================
    conf = classification.get("confidence", 0.0) or 0
    smart_method = classification.get("_smart_method", "none")
    first_turn = len(memory.messages) <= 1
    
    # Update confidence band in memory
    memory.update_confidence_band(conf)
    
    # Determine threshold based on confidence band and method
    if smart_method in ("direct_match", "direct_boosted"):
        threshold = CONFIDENCE_DIRECT_MATCH_THRESHOLD  # 0.50 - trust direct matches
    elif first_turn and describes_problem(user_text):
        threshold = CONFIDENCE_FIRST_TURN_THRESHOLD  # 0.25 - first turn with clear problem
    else:
        threshold = CONFIDENCE_THRESHOLD_LOW  # 0.4 - default minimum
    
    has_hit = bool(classification.get("call_type_code")) and conf >= threshold
    
    logger.info(f"Smart classification: method={smart_method}, conf={conf:.2f}, band={memory.confidence_band}, threshold={threshold}, hit={has_hit}")

    if has_hit:
        _apply_classification_hit(memory, classification)
        # =====================================================================
        # BEHAVIOR CONTRACT RULE 8: Check for missing slots BEFORE proceeding to location
        # Even with high confidence, we need all required information
        # =====================================================================
        if should_use_slot_clarification(memory.candidate_call_types, conf, memory.clarification_count):
            missing_slots = get_missing_slots(memory.candidate_call_types, memory.collected_slots)
            
            if missing_slots and memory.clarification_count < MAX_CLARIFICATION_QUESTIONS:
                # Ask about the most important missing slot
                next_slot = missing_slots[0]
                response = generate_slot_question(next_slot)
                
                # Mark that we're waiting for this slot
                memory.required_slots[next_slot] = None
                
                logger.info(f"High confidence but missing slot '{next_slot}' - asking before location")
                next_state = ConversationState.ISSUE_BUILDING
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # All slots collected or not needed - proceed to location
        next_state = decide_next_state(state_for_logic, classification, memory, user_text)
        if next_state == ConversationState.NEEDS_LOCATION and memory.location:
            next_state = ConversationState.CONFIRMING
        response = generate_response(next_state, memory)
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # =========================================================================
    # BEHAVIOR CONTRACT RULE 5: Clarification Limit (Hard Rule - Max 3)
    # NO HIT: Smart clarification with strict limit
    # =========================================================================
    memory.clarification_count += 1  # Track clarification questions asked
    memory.classification_miss_count += 1
    
    logger.info(f"Clarification attempt {memory.clarification_count}/{MAX_CLARIFICATION_QUESTIONS}")
    
    # Attempt 1-2: Ask targeted clarification questions
    if memory.clarification_count < MAX_CLARIFICATION_QUESTIONS:
        # =====================================================================
        # BEHAVIOR CONTRACT RULE 8: Slot-Based Clarification (Unlock Rare Call Types)
        # Check if we should use slot-based clarification
        # =====================================================================
        if should_use_slot_clarification(memory.candidate_call_types, conf, memory.clarification_count):
            missing_slots = get_missing_slots(memory.candidate_call_types, memory.collected_slots)
            
            if missing_slots:
                # Ask about the most important missing slot
                next_slot = missing_slots[0]
                response = generate_slot_question(next_slot)
                
                # Mark that we're waiting for this slot
                memory.required_slots[next_slot] = None
                
                logger.info(f"Slot-based clarification: asking for '{next_slot}'")
                next_state = ConversationState.ISSUE_BUILDING
                frontend_flags = get_frontend_flags(next_state)
                return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}
        
        # Standard clarification if slot-based doesn't apply
        response = generate_simple_clarification_question(memory)
        next_state = ConversationState.ISSUE_BUILDING
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # Attempt 3: Final clarification (last chance)
    if memory.clarification_count == MAX_CLARIFICATION_QUESTIONS and not memory.we_dont_understand_offered:
        memory.we_dont_understand_offered = True
        response = generate_we_dont_understand_question(memory)
        next_state = ConversationState.ISSUE_BUILDING
        frontend_flags = get_frontend_flags(next_state)
        return {"response": response, "state": next_state, "memory": memory, "frontend_flags": frontend_flags, "classification": classification}

    # After 3 attempts: Force progression with best available candidate
    # BEHAVIOR CONTRACT: A category is chosen because it survived clarification
    if memory.clarification_count >= MAX_CLARIFICATION_QUESTIONS:
        logger.warning(f"Max clarification limit ({MAX_CLARIFICATION_QUESTIONS}) reached. Force progression with best candidate.")
    
    # =====================================================================
    # BEHAVIOR CONTRACT: Force Progression with Best Available Candidate
    # "A category is chosen because it survived clarification"
    # =====================================================================
    # Try to use best candidate from memory first
    best_candidate = memory.get_top_candidate()
    
    if best_candidate and best_candidate.get("call_type_code"):
        # Use the best candidate that survived clarification
        logger.info(f"Force progression: using best candidate {best_candidate.get('short_description')} (conf={best_candidate.get('confidence')})")
        classification = {
            "issue_label": best_candidate.get("short_description"),
            "call_type_code": best_candidate.get("call_type_code"),
            "confidence": best_candidate.get("confidence", 0.5),
        }
        _apply_classification_hit(memory, classification)
    elif classification.get("call_type_code"):
        # Use current classification if available
        logger.info("Force progression: using current classification")
        _apply_classification_hit(memory, classification)
    else:
        # No classification at all - use general fallback
        fallback = get_fallback_general_call_type() or {
            "issue_label": "General enquiry",
            "call_type_code": 15001,
            "confidence": 0.5,
        }
        logger.info("Force progression: using general fallback")
        _apply_classification_hit(memory, fallback)
        classification = fallback
    
    next_state = decide_next_state(state_for_logic, classification, memory, user_text)
    # Use new response structure with selected call type
    from src.conversation.response_generator import generate_response_structure
    response_structure = generate_response_structure(next_state, memory)
    return response_structure


def _apply_classification_hit(memory: CaseMemory, classification: Dict[str, Any]) -> None:
    """Update memory from a successful classification and reset clarification state."""
    code = classification.get("call_type_code")
    if isinstance(code, str):
        try:
            code = int(code)
        except (ValueError, TypeError):
            code = None
    memory.update_issue(
        issue_summary=classification.get("issue_label") or "Issue",
        call_type_code=code,
    )
    # NEW: Store selected call type description for frontend
    if code:
        from src.classification.call_type_matcher import get_call_type_description
        memory.selected_call_type = get_call_type_description(code)
    memory.clarification_count = 0
    memory.classification_miss_count = 0
    memory.we_dont_understand_offered = False


def _build_classification_context(memory: CaseMemory, current_message: str, skip_current: bool = False) -> str:
    """Build context for classification; optionally exclude current message (e.g. when it's location-only)."""
    return build_classification_context(memory, current_message, skip_current=skip_current)


def _contains_problem_keywords(text: str) -> bool:
    """Check if text contains problem-indicating keywords."""
    text_lower = text.lower()
    problem_keywords = [
        "leak", "burst", "broken", "damaged", "not working", "out", "off",
        "blocked", "overflow", "pothole", "sinkhole", "outage", "fire",
        "smoke", "accident", "dumping", "trash", "rubbish", "collection",
        "pressure", "quality", "brown", "dirty", "smell", "sparking",
        "flickering", "stolen", "theft", "fault", "problem", "issue",
        "street light", "traffic light", "power", "electricity", "water",
        "sewer", "drain", "cable", "meter", "bin", "refuse"
    ]
    return any(kw in text_lower for kw in problem_keywords)


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


def handle_user_correction(
    correction_type: str,
    correction_value: Any,
    current_state: ConversationState,
    memory: CaseMemory
) -> Dict[str, Any]:
    # NEW: Clear selected call type when issue is corrected
    if correction_type == "issue":
        memory.selected_call_type = None
    """
    Handle user corrections (issue or location).
    
    correction_type: "issue" or "location"
    correction_value: The corrected value
    """
    if correction_type == "issue":
        # User is correcting the issue
        memory.update_issue(
            issue_summary=str(correction_value),
            call_type_code=None  # Reset code if user corrects
        )
        # Re-classify if needed
        if memory.messages:
            classification = classify_issue(
                text=correction_value,
                conversation_history=memory.messages
            )
            if classification.get("call_type_code"):
                memory.update_issue(
                    issue_summary=classification.get("issue_label", str(correction_value)),
                    call_type_code=classification.get("call_type_code")
                )
    
    elif correction_type == "location":
        memory.update_location(str(correction_value))
    
    # Re-decide state after correction
    classification = classify_issue(
        text=memory.messages[-1] if memory.messages else "",
        conversation_history=memory.messages
    )
    next_state = decide_next_state(current_state, classification, memory)
    
    # Generate response
    response = generate_response(next_state, memory)
    frontend_flags = get_frontend_flags(next_state)
    
    return {
        "response": response,
        "state": next_state,
        "memory": memory,
        "frontend_flags": frontend_flags
    }


def handle_confirmation(
    is_confirmed: bool,
    current_state: ConversationState,
    memory: CaseMemory
) -> Dict[str, Any]:
    # NEW: Clear selected call type when issue is corrected
    if is_confirmed:
        memory.selected_call_type = None
    """
    Handle user confirmation (yes/no).
    """
    if is_confirmed:
        memory.confirm()
        next_state = ConversationState.SUBMITTED
    else:
        # User rejected - go back to issue building
        next_state = ConversationState.ISSUE_BUILDING
    
    response = generate_response(next_state, memory)
    frontend_flags = get_frontend_flags(next_state)
    
    return {
        "response": response,
        "state": next_state,
        "memory": memory,
        "frontend_flags": frontend_flags
    }
