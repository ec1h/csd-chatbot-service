"""
Intent Detector - LLM-based Context-Aware Intent Recognition
============================================================
Uses LLM to understand user intent from conversation context.

Only called for AMBIGUOUS cases where keyword matching might fail.
Does NOT replace existing logic - adds intelligence on top.
"""

import logging
from typing import Dict, List, Optional
from src.core.dspy_pipeline import _configure_lm

logger = logging.getLogger(__name__)


def format_conversation_history(messages: List[str], max_messages: int = 5) -> str:
    """Format recent conversation messages for LLM context"""
    if not messages:
        return "No previous messages"
    
    recent = messages[-max_messages:]
    formatted = []
    for i, msg in enumerate(recent, 1):
        role = "Bot" if i % 2 == 0 else "User"
        formatted.append(f"{role}: {msg[:100]}")  # Limit length
    
    return "\n".join(formatted)


def is_ambiguous_case(user_text: str) -> bool:
    """
    Check if this is an ambiguous case that needs LLM analysis.
    
    Ambiguous = contains navigation words + problem words
    Examples:
    - "i want my pipe to change" (problem with "change")
    - "can i change the issue" (navigation with "change")
    - "the location needs fixing" (location + problem word)
    
    Clear cases DON'T need LLM:
    - "burst pipe" (obvious problem)
    - "nevermind" (obvious navigation)
    - "123 main street" (obvious location)
    """
    text_lower = user_text.lower()
    
    # Navigation indicators
    navigation_words = ["change", "fix", "correct", "update", "modify", "redo", "restart", "nevermind", "cancel"]
    meta_words = ["issue", "problem", "location", "address", "report"]
    
    # Problem indicators
    problem_words = ["burst", "broken", "leak", "leaking", "flood", "overflow", "blocked", 
                     "damaged", "missing", "stuck", "faulty", "not working", "out"]
    
    has_navigation = any(word in text_lower for word in navigation_words)
    has_meta = any(word in text_lower for word in meta_words)
    has_problem = any(word in text_lower for word in problem_words)
    
    # Ambiguous if:
    # 1. Has navigation word + problem word (e.g., "pipe needs to change")
    # 2. Has navigation word + meta word (e.g., "change the issue")
    # But ONLY if message is reasonably long (>3 words) - short ones are usually clear
    word_count = len(user_text.split())
    
    if word_count < 3:
        return False  # Short messages are usually clear
    
    is_ambiguous = (has_navigation and has_problem) or (has_navigation and has_meta and word_count > 5)
    
    if is_ambiguous:
        logger.info(f"Detected ambiguous case: '{user_text[:60]}...' (nav:{has_navigation}, meta:{has_meta}, problem:{has_problem})")
    
    return is_ambiguous


def detect_intent_with_llm(user_text: str, conversation_history: List[str]) -> Dict[str, any]:
    """
    Use LLM to detect user intent in context.
    
    Returns:
    {
        'intent': 'navigation' | 'problem_description' | 'information_provision' | 'unclear',
        'confidence': float,
        'reasoning': str
    }
    """
    
    try:
        # Format conversation context
        history_text = format_conversation_history(conversation_history)
        
        # Create prompt for intent detection
        prompt = f"""Analyze the conversation and determine the user's intent.

Recent conversation:
{history_text}

User's latest message: "{user_text}"

Determine the user's PRIMARY intent:

A) NAVIGATION - User wants to change/navigate our conversation flow
   Examples: "change the issue", "i want to report something else", "nevermind"
   Key: They're talking ABOUT the conversation itself (meta-language)

B) PROBLEM_DESCRIPTION - User is describing an actual problem
   Examples: "my pipe is leaking", "the pipe needs to change" (deteriorating), "light is broken"
   Key: They're describing a real-world issue, even if using words like "change"

C) INFORMATION_PROVISION - User is providing requested information
   Examples: "123 main street" (responding to location request), "yes" (confirming)
   Key: They're answering a question

Semantic context is crucial:
- "pipe needs to change" (pipe deteriorating) = PROBLEM_DESCRIPTION
- "change the issue" (modify conversation) = NAVIGATION
- "i want to change this to water leak" = NAVIGATION (changing conversation topic)

Respond ONLY with the letter (A, B, or C):"""

        # Call LLM
        lm = _configure_lm()
        raw_response = lm(prompt)
        
        # Handle different response formats (string or list)
        if isinstance(raw_response, list):
            response = str(raw_response[0]) if raw_response else 'B'
        else:
            response = str(raw_response)
        
        response = response.strip().upper()
        
        # Parse response
        intent_map = {
            'A': 'navigation',
            'B': 'problem_description',
            'C': 'information_provision'
        }
        
        intent = intent_map.get(response[0] if response else 'B', 'problem_description')
        
        logger.info(f"LLM intent detection: '{user_text[:40]}...' -> {intent} (raw: {response})")
        
        return {
            'intent': intent,
            'confidence': 0.85,  # LLM-based, generally reliable
            'reasoning': f'LLM classified as {response}'
        }
        
    except Exception as e:
        logger.error(f"LLM intent detection failed: {e}")
        # Safe fallback: assume problem description (most common case)
        return {
            'intent': 'problem_description',
            'confidence': 0.3,
            'reasoning': f'Fallback due to error: {str(e)}'
        }


def detect_confirmation_intent(user_text: str, conversation_history: List[str]) -> str:
    """
    Detect user's intent in a confirmation context using LLM.
    
    Returns one of:
    - "AFFIRM": User is confirming/agreeing (yes, correct, looks good, etc.)
    - "DENY": User is rejecting/disagreeing (no, wrong, not that, nah, etc.)
    - "CORRECT": User wants to change/fix something
    - "UNSURE": User is uncertain/hesitant (wait, maybe, not sure, etc.)
    - "UNCLEAR": Cannot determine intent
    
    This is SEMANTIC detection - it understands intent, not just keywords.
    Humans don't say "no" consistently - they say "not that", "nah", "eish no", etc.
    """
    try:
        lm = _configure_lm()
        
        # Format conversation context
        history_str = format_conversation_history(conversation_history, max_messages=3)
        
        # Create a focused prompt for confirmation intent detection
        prompt = f"""You are analyzing a user's response in a confirmation dialog.

Recent conversation:
{history_str}

User's current message: "{user_text}"

The bot just asked the user to confirm something (an issue classification or location).

Classify the user's intent as ONE of these:
A) AFFIRM - User is confirming/agreeing (examples: "yes", "correct", "looks good", "that's right", "yep", "yeah", "ok", "sure", "exactly", "right")
B) DENY - User is rejecting/disagreeing (examples: "no", "wrong", "not that", "nah", "eish no", "that's not right", "you got it wrong", "incorrect")
C) CORRECT - User wants to change/modify something (examples: "can I change", "let me fix that", "I meant something else", "actually it's...")
D) UNSURE - User is uncertain/hesitant (examples: "wait", "hold on", "maybe", "not sure", "I think", "probably")
E) UNCLEAR - Cannot determine intent from the message

CRITICAL: Do NOT rely on specific keywords. Understand the SEMANTIC INTENT.
- "not that" = DENY (not a keyword match, but clear rejection)
- "something else" = CORRECT (wants to change)
- "good" = AFFIRM (positive affirmation)
- "nah" = DENY (informal no)

Reply with ONLY the letter: A, B, C, D, or E"""

        # Call LLM
        raw_response = lm(prompt)
        
        # Handle list response
        if isinstance(raw_response, list):
            response = str(raw_response[0])
        else:
            response = str(raw_response)
        
        response = response.strip().upper()
        
        # Parse response
        intent_map = {
            "A": "AFFIRM",
            "B": "DENY",
            "C": "CORRECT",
            "D": "UNSURE",
            "E": "UNCLEAR"
        }
        
        # Extract just the letter if there's extra text
        for letter in ["A", "B", "C", "D", "E"]:
            if letter in response:
                intent = intent_map[letter]
                logger.info(f"Semantic intent detected: '{user_text[:50]}...' → {intent}")
                return intent
        
        logger.warning(f"Could not parse LLM response: {response}")
        return "UNCLEAR"
        
    except Exception as e:
        logger.warning(f"Semantic intent detection failed: {e}")
        return "UNCLEAR"


def should_handle_as_navigation(user_text: str, conversation_history: List[str]) -> bool:
    """
    Determine if user input should be handled as navigation.
    
    This is the MAIN function called by orchestrator.
    
    Strategy:
    1. Quick checks for obvious cases (fast, no LLM)
    2. Only use LLM for ambiguous cases
    3. Safe defaults
    """
    
    # Quick check 1: Very short phrases are usually not ambiguous
    if len(user_text.split()) <= 2:
        text_lower = user_text.lower().strip()
        # Direct navigation commands
        if text_lower in ["issue", "the issue", "location", "the location", "nevermind", "cancel", "restart"]:
            logger.info(f"Quick navigation detect: '{user_text}'")
            return True
        return False
    
    # Quick check 2: Clear problem descriptions (no LLM needed)
    text_lower = user_text.lower()
    obvious_problems = ["burst", "leaking", "flooding", "overflow", "stuck", "missing", "stolen", "damaged"]
    if any(word in text_lower for word in obvious_problems) and "change the" not in text_lower:
        # Has obvious problem word and NOT talking about changing our conversation
        return False
    
    # Quick check 3: Is this even ambiguous?
    if not is_ambiguous_case(user_text):
        # Not ambiguous, use existing logic
        return False
    
    # Ambiguous case - use LLM
    logger.info(f"Using LLM for ambiguous case: '{user_text[:60]}...'")
    result = detect_intent_with_llm(user_text, conversation_history)
    
    return result['intent'] == 'navigation'
