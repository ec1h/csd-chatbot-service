"""
Call type matching and classification functions.
Extracted from app.py to reduce app.py size.
"""

import re
import logging
import math
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process

from src.classification.semantic_concepts import detect_concepts, apply_concept_adjustments
from src.classification.embeddings import get_semantic_score, get_semantic_matches
from src.utils.data_loader import (
    load_all_json_call_types,
    get_call_types_by_intent,
    ALL_CALL_TYPES_CACHE,
)

logger = logging.getLogger(__name__)

# Known words for typo correction
KNOWN_WORDS = [
    "water", "electricity", "pothole", "sewage", "meter", "pipe", "burst", "leak",
    "outage", "power", "street", "light", "traffic", "signal", "road", "damage",
    "blockage", "collection", "dumping", "fire", "emergency", "medical", "ambulance",
    "bus", "transport", "pest", "noise", "billing", "account", "payment", "prepaid",
    "token", "voucher", "pressure", "supply", "connection", "illegal", "bypass",
    "tap", "taps", "dry", "flooding", "gushing", "dripping", "cable", "pole",
    "sparking", "flickering", "blackout", "lights", "dark", "broken", "damaged",
    "stolen", "bees", "accident", "rescue", "trapped", "gas", "smoke", "burning",
    "metro bus", "metrobus", "bus stop", "bus route", "bus card", "bus driver",
    "bus seats", "bus dirty", "bus is", "bus are", "bus late", "bus not",
    "bus damaged", "dirty bus", "filthy bus", "unclean bus", "seats are dirty",
    "inside bus dirty", "bus shelter", "bus timetable", "bus schedule", "bus fare",
    "bus ticket", "bus pass", "bus transfer", "bus route change", "bus detour",
    "bus replacement", "bus diversion", "bus service", "bus frequency", "bus capacity",
    "bus overcrowding", "bus maintenance", "bus breakdown", "bus accident", "bus fire",
    "bus emergency", "bus safety", "bus security", "bus theft", "bus vandalism",
    "bus graffiti", "bus litter", "bus cleanliness", "bus hygiene", "bus smell",
    "bus odor", "bus pest", "bus rat", "bus cockroach", "bus infestation",
    "bus noise", "bus loud", "bus music", "bus disturbance", "bus complaint",
    "bus compliment", "bus feedback", "bus enquiry", "bus information", "bus help",
    "bus support", "bus contact", "bus staff", "bus driver behaviour", "bus reckless",
    "bus rude", "bus aggressive", "bus dangerous", "bus speeding", "bus running red light",
    "bus illegal", "bus by law", "bus zoning", "bus land use", "bus illegal construction",
    "bus illegal building", "bus general", "bus general enquiry", "bus general information",
    "bus complaint about", "bus compliment", "bus feedback", "bus building plan",
    "bus zoning enquiry", "bus staff complaint", "bus service complaint", "bus illegal construction",
    "bus illegal building", "bus general enquiry", "bus general information"
]


def compute_final_score(
    keyword_score: float,
    semantic_score: float,
    tfidf_score: float = 0.0,
    exact_match: bool = False
) -> float:
    """
    PHASE 3: Multi-signal fusion - combine all signals with learned weights.
    
    Args:
        keyword_score: Score from keyword matching (0-1)
        semantic_score: Score from embeddings (0-1)
        tfidf_score: Score from TF-IDF (0-1), defaults to 0 if not available
        exact_match: True if exact phrase match found
        
    Returns:
        Final combined score (0-1)
    """
    if exact_match:
        return 1.0  # Exact match always wins
    
    # Weights (should sum to 1.0)
    W_KEYWORD = 0.3
    W_SEMANTIC = 0.5  # Semantic gets highest weight
    W_TFIDF = 0.2
    
    return (
        W_KEYWORD * keyword_score +
        W_SEMANTIC * semantic_score +
        W_TFIDF * tfidf_score
    )


def calculate_calibrated_confidence(top_matches: List[Dict]) -> float:
    """
    PHASE 5: Calculate confidence based on score distribution using entropy.
    High confidence = one match dominates.
    Low confidence = scores are spread out.
    
    Args:
        top_matches: List of match dictionaries with 'confidence' scores
        
    Returns:
        Calibrated confidence score (0-1)
    """
    if not top_matches:
        return 0.0
    
    scores = [m.get("confidence", 0) for m in top_matches[:5]]
    total = sum(scores)
    if total == 0:
        return 0.0
    
    # Normalize to probabilities
    probs = [s / total for s in scores if s > 0]
    
    if not probs:
        return 0.0
    
    # Calculate entropy (0 = certain, high = uncertain)
    entropy = -sum(p * math.log2(p + 1e-10) for p in probs if p > 0)
    max_entropy = math.log2(len(probs)) if len(probs) > 1 else 1.0  # Maximum possible entropy
    
    # Convert to confidence (0-1, higher = more confident)
    normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
    
    # Combine with top score
    top_score = scores[0] if scores else 0
    confidence = top_score * (1 - normalized_entropy * 0.5)  # Entropy reduces confidence
    
    return min(1.0, max(0.0, confidence))


def correct_typos(text: str) -> str:
    """
    Correct common typos in user input before matching.
    Uses fuzzy matching to fix typos like "electrisity" -> "electricity".
    
    Args:
        text: User input text
        
    Returns:
        Text with typos corrected
    """
    words = text.lower().split()
    corrected = []
    for word in words:
        if len(word) > 3:  # Only correct longer words
            match = process.extractOne(word, KNOWN_WORDS, scorer=fuzz.ratio)
            if match and match[1] > 80:  # 80% similarity threshold
                corrected.append(match[0])
            else:
                corrected.append(word)
        else:
            corrected.append(word)
    return " ".join(corrected)


# Confidence thresholds
CONFIDENCE_THRESHOLD_MIN = 0.25        # Minimum to even consider a match candidate (lowered for better discovery)
CONFIDENCE_THRESHOLD_ASK = 0.45        # Below this: MUST ask clarifying questions (lowered for faster matching)
CONFIDENCE_THRESHOLD_CONFIRM = 0.65    # Below this but above ASK: MUST confirm with user (lowered for better UX)
CONFIDENCE_THRESHOLD_LOCK = 0.70       # At or above this: can auto-lock classification (lowered for seamless flow)

# Legacy threshold (deprecated - use the gating thresholds above)
CONFIDENCE_THRESHOLD_AUTO = 0.55  # Kept for backward compatibility, but gating rules take precedence


# Problem groups for hierarchical classification
PROBLEM_GROUPS = {
    "water": {
        "outage": ["no water", "no supply", "water cut", "dry taps", "nothing coming"],
        "leak": ["leak", "burst", "gushing", "water running", "flooding", "drip"],
        "quality": ["dirty", "discolored", "smell", "brown water", "contaminated", "pressure"],
        "blockage": ["blocked", "sewage", "sewer", "overflow", "manhole", "drain"],
        "meter": ["meter", "reading", "consumption"],
        "billing": ["bill", "account", "statement", "payment"]
    },
    "electricity": {
        "outage": ["no power", "no electricity", "blackout", "power off", "lights off", "dark"],
        "street_lighting": ["street light", "street lamp", "light pole", "public light", "pavement light"],
        "fault": ["sparks", "sparking", "cable", "exposed wire", "flickering", "surge"],
        "meter": ["prepaid", "meter", "token", "vend", "error code"],
        "billing": ["bill", "account", "statement", "payment"]
    },
    "roads": {
        "surface": ["pothole", "crack", "damage", "tar", "gravel", "road surface"],
        "signage": ["sign", "road marking", "paint", "lines", "faded"],
        "traffic": ["traffic light", "traffic signal", "robot"],
        "infrastructure": ["bridge", "culvert", "pavement", "sidewalk", "kerb"]
    },
    "waste": {
        "collection": ["not collected", "missed", "bin", "refuse", "garbage"],
        "dumping": ["illegal dumping", "dumping", "fly tipping", "rubble"],
        "animal": ["dead animal", "carcass", "roadkill", "dead dog", "dead cat"],
        "litter": ["litter", "rubbish", "clean up"]
    },
    "emergency": {
        "fire": ["fire", "burning", "smoke", "flames", "wildfire"],
        "medical": ["ambulance", "injured", "accident", "emergency medical"],
        "rescue": ["trapped", "rescue", "stuck"],
        "hazmat": ["gas leak", "chemical", "toxic", "hazardous", "spill"]
    },
    "transport": {
        "service": ["bus late", "didn't arrive", "non arrival", "delayed", "cancelled"],
        "driver": ["rude driver", "reckless", "driver behaviour", "complaint about driver"],
        "card": ["lost card", "lost tag", "card issue", "tap card"],
        "stop": ["bus stop", "shelter", "route"],
        # Hygiene / quality issues for transport assets (e.g. dirty bus seats)
        "quality": [
            "dirty bus",
            "dirty seats",
            "bus seats",
            "seats are dirty",
            "unclean bus",
            "filthy bus",
            "inside bus dirty",
        ],
    },
    "health": {
        "pest": ["rat", "rats", "cockroach", "pest", "mouse", "mice", "infestation"],
        "noise": ["noise", "loud", "music", "disturbance"],
        "food": ["food poisoning", "restaurant", "vendor", "food safety", "hygiene"],
        "pollution": ["pollution", "air quality", "smell", "odor", "stagnant"]
    },
    "billing": {
        "query": ["query", "question", "enquiry", "understand"],
        "dispute": ["wrong", "incorrect", "dispute", "overcharged", "too high"],
        "payment": ["payment", "pay", "settle", "arrange"],
        "refund": ["refund", "credit", "owed"]
    },
    "general": {
        "complaint": ["complaint", "complain", "unhappy", "dissatisfied"],
        "compliment": ["compliment", "thank", "good service", "well done"],
        "enquiry": ["enquiry", "information", "how do i", "where is"]
    }
}


# Negative evidence scoring matrix
NEGATIVE_EVIDENCE_SCORES = {
    # Electricity vs Street Lighting confusion
    "street light": {"electricity outage": -0.5, "no power": -0.4, "blackout": -0.3},
    "street lamp": {"electricity outage": -0.5, "no power": -0.4},
    "light pole": {"electricity outage": -0.4, "no power": -0.3},
    "public light": {"electricity outage": -0.4},

    # Street Lighting vs Home Power confusion
    "inside house": {"street light": -0.4, "public light": -0.5},
    "in my house": {"street light": -0.4, "public light": -0.5},
    "my property": {"street light": -0.3, "public light": -0.4},
    "at home": {"street light": -0.3, "public light": -0.4},
    "my house": {"street light": -0.3},

    # Water vs Electricity confusion
    "geyser element": {"water leak": -0.3, "burst pipe": -0.4},
    "geyser burst": {"electricity": -0.5},
    "hot water": {"electricity outage": -0.3},

    # Roads vs Water confusion (stormwater)
    "storm water": {"water supply": -0.4, "no water": -0.5},
    "stormwater": {"water supply": -0.4, "no water": -0.5},
    "flooding road": {"burst pipe": -0.3},

    # Waste vs Health confusion
    "food waste": {"pest": -0.3, "rodent": -0.3},
    "restaurant waste": {"refuse collection": -0.3},

    # Billing cross-department
    "water bill": {"electricity billing": -0.5, "rates": -0.3},
    "electricity bill": {"water billing": -0.5, "rates": -0.3},
    "rates bill": {"water billing": -0.3, "electricity billing": -0.3},

    # Emergency vs Non-emergency
    "old fire": {"active fire": -0.5, "fire emergency": -0.5},
    "fire damage": {"active fire": -0.4, "fire emergency": -0.4},
    "after the fire": {"active fire": -0.5},

    # Street/Public leak vs Meter leak confusion
    # When user mentions street/road/pavement, penalize meter-related call types
    "street": {"meter leak": -0.5, "meter": -0.4},
    "in the street": {"meter leak": -0.6, "meter": -0.5},
    "on the street": {"meter leak": -0.6, "meter": -0.5},
    "my street": {"meter leak": -0.5, "meter": -0.4},
    "road": {"meter leak": -0.4, "meter": -0.3},
    "pavement": {"meter leak": -0.5, "meter": -0.4},
    "outside": {"meter leak": -0.3},
    "public": {"meter leak": -0.4, "meter": -0.3},

    # Meter leak vs Street/Pipe leak - when user mentions meter, penalize street/pipe types
    "my meter": {"burst pipe": -0.3, "underground": -0.3},
    "water meter": {"burst pipe": -0.3, "underground": -0.3},
    "at the meter": {"burst pipe": -0.4, "underground": -0.4},
}


# is_vague_input
def is_vague_input(user_text: str) -> bool:
    """
    Check if user input is too vague (insufficient information to identify specific issue).
    This is category-agnostic and works for ALL service types.

    A vague input is one that:
    1. Only mentions a category/service name without describing the problem
    2. Is too short (< 3 words) and lacks specific problem indicators
    3. Uses generic phrases like "issue", "problem" without details
    """
    text_lower = user_text.lower().strip()
    words = text_lower.split()
    word_count = len(words)

    # Very short inputs (1-2 words) are almost always vague unless they're specific problem terms WITH context
    # Single-word category mentions (water, fire, electricity, etc.) are ALWAYS vague
    # EXCEPT for "bus" when it's part of a transport query
    single_word_category_mentions = [
        "water", "electricity", "electric", "power", "transport", "roads", "road",
        "waste", "emergency", "fire", "health", "billing", "general"
    ]

    if word_count == 1:
        # Single word inputs are vague if they're just category mentions
        if text_lower.strip() in single_word_category_mentions:
            return True
        # Even if it's a problem term, single words without context are vague
        specific_problem_terms = [
            "leak", "burst", "outage", "broken", "damaged", "missing", "blocked",
            "overflow", "flooding", "sparking", "flickering", "no water", "no power",
            "late", "delayed", "overcrowded", "pothole", "crack"
        ]
        # Single word problem terms without additional context are still vague
        if text_lower.strip() in specific_problem_terms:
            return True
        # Special case: "bus" alone should not be vague if it's a transport query
        if text_lower.strip() == "bus":
            # Check if it could be a transport query by looking at context
            # This is a special case where "bus" alone should be considered
            # as a potential transport query rather than vague
            return False

    if word_count == 2:
        # Two-word inputs are vague if they're just category + generic word
        specific_problem_terms = [
            "leak", "burst", "outage", "broken", "damaged", "missing", "blocked",
            "overflow", "flooding", "sparking", "flickering", "no water", "no power",
            "late", "delayed", "overcrowded", "pothole", "crack",
            # Water-specific two-word terms
            "illegal connection", "water leak", "burst pipe", "no water", "water pressure",
            "water meter", "sewer blockage", "pipe burst", "water cut",
            # Electricity-specific two-word terms
            "power outage", "no power", "street light", "prepaid meter", "power cable",
            # Other specific two-word problem terms
            "traffic light", "bus stop", "bus route", "bin collection", "illegal dumping",
            # Transport-specific two-word terms
            "bus late", "bus not", "bus route", "bus stop", "bus card", "bus driver",
            "bus seats", "bus dirty", "bus is", "bus are"
        ]
        # Check if the entire 2-word phrase is a specific problem term
        if text_lower.strip() in specific_problem_terms:
            return False
        # If it's just 2 words and none are specific problem terms, it's vague
        if not any(term in text_lower for term in specific_problem_terms):
            return True

    # Specific keywords that indicate a clear issue (across all categories)
    specific_keywords = [
        # Water
        "leak", "burst", "pipe", "no water", "water pressure", "low pressure",
        "geyser", "tap", "sewer", "drain", "meter", "dripping", "flooding",
        "illegal connection", "connection bypass", "bypass meter", "water connection",
        "illegal conn", "water meter", "burst pipe", "sewer blockage",
        # Electricity
        "outage", "no power", "no electricity", "blackout", "cable", "pole",
        "street light", "prepaid", "lights", "no lights", "sparking", "flickering",
        "prepaid meter", "power outage", "power cable",
        # Transport
        "bus late", "bus not running", "bus stop", "bus route", "bus damaged",
        "dirty bus", "bus seats", "dirty seats", "filthy bus", "unclean bus",
        "metro bus", "metrobus", "bus is", "bus are", "bus card", "bus driver",
        "bus shelter", "bus timetable", "bus schedule", "bus fare", "bus ticket",
        "bus pass", "bus transfer", "bus route change", "bus detour", "bus replacement",
        "bus diversion", "bus service", "bus frequency", "bus capacity", "bus overcrowding",
        "bus maintenance", "bus breakdown", "bus accident", "bus fire", "bus emergency",
        "bus safety", "bus security", "bus theft", "bus vandalism", "bus graffiti",
        "bus litter", "bus cleanliness", "bus hygiene", "bus smell", "bus odor",
        "bus pest", "bus rat", "bus cockroach", "bus infestation", "bus noise",
        "bus loud", "bus music", "bus disturbance", "bus complaint", "bus compliment",
        "bus feedback", "bus enquiry", "bus information", "bus help", "bus support",
        "bus contact", "bus staff", "bus driver behaviour", "bus reckless", "bus rude",
        "bus aggressive", "bus dangerous", "bus speeding", "bus running red light",
        "bus illegal", "bus by law", "bus zoning", "bus land use", "bus illegal construction",
        "bus illegal building", "bus general", "bus general enquiry", "bus general information",
        "bus complaint about", "bus compliment", "bus feedback", "bus building plan",
        "bus zoning enquiry", "bus staff complaint", "bus service complaint", "bus illegal construction",
        "bus illegal building", "bus general enquiry", "bus general information",
        # Roads
        "pothole", "crack", "road damage", "traffic light", "robot", "sign",
        # Waste
        "bin", "refuse", "garbage", "dumping", "collection",
        # Emergency
        "fire", "smoke", "accident", "medical",
        # General - hygiene/cleanliness issues
        "broken", "damaged", "missing", "blocked", "overflow",
        "dirty", "filthy", "unclean", "messy", "smelly", "stained",
    ]

    # If input contains any specific keyword, it's NOT vague
    if any(keyword in text_lower for keyword in specific_keywords):
        return False

    # Default: if nothing specific found, it's vague
    return True


# reduce_candidates
def reduce_candidates(
    intent_bucket: Optional[str],
    problem_group: Optional[str],
    conversation_history: List[str],
    all_call_types: List[Dict],
    top_k: int = 20
) -> List[Dict]:
    """
    TASK 1: Pre-filter call types to top-K candidates before expensive scoring.

    Filters by (in order of priority):
    1. intent_bucket match (required if provided)
    2. problem_group / issue_category alignment
    3. Historical conversation signals (keywords from prior turns)

    Returns: Reduced list of call type candidates (max top_k)
    """
    if not all_call_types:
        return []

    candidates = all_call_types

    # FILTER 1: Intent bucket (hard filter - dramatically reduces search space)
    # But also include "general" bucket call types as they might be relevant
    # are in "general" bucket but get detected as "roads", "water", "electricity", etc.
    # This ensures they're still considered during matching.
    if intent_bucket:
        bucket_filtered = [
            ct for ct in candidates
            if ct.get("intent_bucket", "").lower() == intent_bucket.lower()
        ]
        # Also include "general" bucket call types to catch mismatches
        # Examples: bollards, kerbs, barriers, footways detected as "roads" but in "general"
        #           water/power infrastructure complaints detected as "water"/"electricity" but in "general"
        if intent_bucket.lower() != "general":
            general_filtered = [
                ct for ct in candidates
                if ct.get("intent_bucket", "").lower() == "general"
            ]
            # Combine both, with priority to the detected bucket
            bucket_filtered = bucket_filtered + general_filtered

        # Only apply filter if it yields results
        if bucket_filtered:
            candidates = bucket_filtered

    # FILTER 2: Problem group alignment via issue_category
    # Maps problem_group to likely issue_categories for further reduction
    if problem_group and len(candidates) > top_k:
        problem_to_category = {
            "outage": ["supply", "maintenance"],
            "leak": ["maintenance", "damage"],
            # Include explicit quality/hygiene categories so transport quality
            # issues (like DIRTY BUS) are not filtered out.
            "quality": ["maintenance", "supply", "quality", "hygiene"],
            "blockage": ["blockage", "maintenance"],
            "meter": ["maintenance", "damage"],
            "billing": ["billing", "query"],
            "street_lighting": ["maintenance"],
            "fault": ["maintenance", "damage"],
            "surface": ["maintenance", "damage"],
            "signage": ["maintenance", "damage"],
            "traffic": ["maintenance"],
            "collection": ["collection", "maintenance"],
            "dumping": ["illegal", "maintenance"],
            "fire": ["emergency"],
            "medical": ["emergency"],
            "pest": ["pest", "health"],
            "noise": ["noise", "nuisance"],
        }

        likely_categories = problem_to_category.get(problem_group, [])
        if likely_categories:
            category_filtered = [
                ct for ct in candidates
                if ct.get("issue_category", "").lower() in likely_categories
            ]
            # Keep filter only if it yields meaningful results
            if len(category_filtered) >= 5:
                candidates = category_filtered

    # FILTER 3: Historical conversation signals
    # Extract keywords from last 3 conversation turns to boost relevant candidates
    if conversation_history and len(candidates) > top_k:
        history_text = " ".join(conversation_history[-3:]).lower()
        history_words = set(history_text.split())

        # Score candidates by overlap with conversation history
        scored = []
        for ct in candidates:
            keywords = ct.get("keywords", [])
            overlap = sum(1 for kw in keywords if kw.lower() in history_text)
            # Also check if any keyword words appear
            keyword_words = set(" ".join(keywords).lower().split())
            word_overlap = len(history_words & keyword_words)
            scored.append((ct, overlap * 2 + word_overlap))

        # Sort by historical relevance and take top candidates
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [ct for ct, _ in scored[:top_k * 2]]  # Keep 2x for scoring phase

    return candidates[:top_k * 2]  # Return up to 2x top_k for final scoring


# detect_problem_group
def detect_problem_group(user_text: str, intent_bucket: str) -> Optional[str]:
    """
    QA STEP 2 - Stage 2: Detect the problem group within an intent bucket.
    This narrows down from domain to problem type BEFORE selecting exact call type.

    Returns: problem group name or None if unclear
    """
    if not intent_bucket or intent_bucket not in PROBLEM_GROUPS:
        return None

    text_lower = user_text.lower()
    group_keywords = PROBLEM_GROUPS[intent_bucket]

    # Score each problem group
    scores = {}
    for group, keywords in group_keywords.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += 1
        if score > 0:
            scores[group] = score

    if not scores:
        return None

    # Return group with highest score
    return max(scores, key=scores.get)


# calculate_negative_evidence_score
def calculate_negative_evidence_score(
    user_text: str,
    call_type_description: str,
    issue_category: str
) -> float:
    """
    QA STEP 3: Calculate negative evidence penalty for a call type.

    Returns: negative score (0.0 = no penalty, negative values = penalty)
    """
    text_lower = user_text.lower()
    call_type_lower = call_type_description.lower()
    category_lower = (issue_category or "").lower()

    total_penalty = 0.0

    for phrase, penalties in NEGATIVE_EVIDENCE_SCORES.items():
        if phrase in text_lower:
            for pattern, penalty in penalties.items():
                # Check if this call type matches the penalty pattern
                if pattern in call_type_lower or pattern in category_lower:
                    total_penalty += penalty

    return total_penalty


# match_call_types_from_json
def match_call_types_from_json(
    user_text: str,
    intent_bucket: Optional[str] = None,
    problem_group: Optional[str] = None,
    conversation_history: Optional[List[str]] = None,
    state: Optional[Dict[str, Any]] = None
) -> List[Dict]:
    """
    Match user text against JSON call types using keyword matching with confidence scoring.
    This uses the refined JSON data with keywords, negative_keywords, and confidence weights.

    ENHANCED FOR BETTER CONTEXT AWARENESS:
    - Aggregates full conversation history for semantic understanding
    - Broader candidate search when confidence is low
    - Better handling of short and long inputs
    - All call types discoverable regardless of input style

    TASK 1: Uses candidate reduction to pre-filter before scoring
    TASK 2: Uses problem_group for hierarchical filtering
    TASK 4: Enhanced confidence combines keyword strength + repetition + contradictions
    TASK 5: Returns ambiguity flag when top matches are too close
    CONCEPT LAYER: Applies semantic concept detection for department gating and scoring

    Returns list of matches sorted by confidence score, each with:
    - call_type_code, short_description, confidence, department, intent_bucket
    - _ambiguous: True if top 2 scores are within 0.05 (requires clarification)
    """
    # Load JSON data if not already loaded (imported from data_loader)
    if not ALL_CALL_TYPES_CACHE:
        load_all_json_call_types()

    # =============================================================================
    # ENHANCEMENT: Aggregate full conversation context for better understanding
    # Combine current message with all previous messages for semantic matching
    # =============================================================================
    history = conversation_history or []
    if state and not history:
        # Extract history from state if available
        history = state.get("conversationHistory", [])

    # Build comprehensive context from conversation history
    # Include recent messages (last 5) plus current message for better context
    if history:
        recent_history = history[-5:] if len(history) > 5 else history
        # Combine recent history with current message for semantic matching
        combined_context = " ".join(recent_history) + " " + user_text
    else:
        combined_context = user_text

    # =============================================================================
    # SEMANTIC CONCEPT LAYER - Detect concepts before matching
    # Use combined context for better concept detection
    # =============================================================================
    concept_result = detect_concepts(combined_context)

    # Log detected concepts for debugging
    if concept_result.detected_concepts:
        detected_names = [cm.concept.name for cm in concept_result.detected_concepts]
        logger.info(f"Detected concepts: {detected_names}")

    # Override intent_bucket if concepts strongly constrain departments
    if not intent_bucket and concept_result.allowed_departments:
        # Use the first allowed department as the intent bucket
        allowed_list = list(concept_result.allowed_departments - concept_result.blocked_departments)
        if len(allowed_list) == 1:
            intent_bucket = allowed_list[0]
            logger.info(f"Concept layer set intent_bucket to: {intent_bucket}")

    # =============================================================================
    # PHASE 1: TYPO TOLERANCE - Correct typos before matching
    # =============================================================================
    # Apply typo correction to the combined context
    corrected_context = correct_typos(combined_context)
    logger.debug(f"Typo correction: '{combined_context}' -> '{corrected_context}'")
    
    # Use corrected context for matching (better semantic understanding)
    text_lower = corrected_context.lower()

    # Enhanced synonym expansion: map common user terms to technical terms used in call types
    synonym_mappings = {
        # Prepaid meter synonyms
        "voucher": "token",
        "hasn't loaded": "token failed",
        "hasn't worked": "token failed",
        "didn't load": "token failed",
        "not loading": "token failed",
        "won't load": "token failed",
        "not accepted": "token rejected",
        "won't accept": "token rejected",
        "code not working": "token failed",
        "entered the code": "prepaid token",
        "add credit": "prepaid",
        "top up": "prepaid",
        "topup": "prepaid",
        "recharge": "prepaid",
        # Water-related synonyms
        "water pressure low": "low water pressure",
        "water pressure is low": "low water pressure",
        "weak water": "low water pressure",
        "trickling": "low water pressure",
        "slow flow": "low water pressure",
        "water comes and goes": "intermittent water supply",
        "water intermittent": "intermittent water supply",
        "water on and off": "intermittent water supply",
        "no water from taps": "no water",
        "dry taps": "no water",
        "water outage": "no water",
        # Electricity-related synonyms
        "power out": "no supply",
        "no power": "no supply",
        "electricity out": "no supply",
        "blackout": "no supply",
        "lights off": "no supply",
        "power outage": "no supply",
        # General synonyms
        "no change": "not working",
        "still shows": "not working",
        "broken": "damaged",
        "not working": "faulty",
        # Bollard and road infrastructure synonyms
        "bollard": "municipal bollard",
        "bollards": "municipal bollard",
        "damaged bollard": "municipal bollard repair",
        "broken bollard": "municipal bollard repair",
        "knocked over bollard": "municipal bollard repair",
        "fallen bollard": "municipal bollard repair",
        "bollard damaged": "municipal bollard repair",
        "bollard broken": "municipal bollard repair",
        "bollard needs repair": "municipal bollard repair",
        "bollard needs fixing": "municipal bollard repair",
        "bollard inspection": "municipal bollard repair",
        "municipal bollard": "municipal bollard repair",
        # Road and infrastructure terms
        "road barrier": "guardrail",
        "traffic barrier": "guardrail",
        "safety barrier": "guardrail",
        "road sign damaged": "damaged road sign",
        "traffic sign broken": "damaged road sign",
        "street sign": "road sign",
        # Pothole variations
        "hole in road": "pothole",
        "road hole": "pothole",
        "crack in road": "pothole",
        "road damage": "pothole",
        # Bus-related synonyms
        "metro bus": "metrobus",
        "metrobus": "metrobus",
        "bus stop": "bus stop",
        "bus route": "bus route",
        "bus card": "bus card",
        "bus driver": "bus driver",
        "bus seats": "bus seats",
        "bus dirty": "dirty bus",
        "bus is": "bus is",
        "bus are": "bus are",
        "bus late": "bus late",
        "bus not": "bus not running",
        "bus damaged": "bus damaged",
        "bus shelter": "bus shelter",
        "bus timetable": "bus timetable",
        "bus schedule": "bus schedule",
        "bus fare": "bus fare",
        "bus ticket": "bus ticket",
        "bus pass": "bus pass",
        "bus transfer": "bus transfer",
        "bus route change": "bus route change",
        "bus detour": "bus detour",
        "bus replacement": "bus replacement",
        "bus diversion": "bus diversion",
        "bus service": "bus service",
        "bus frequency": "bus frequency",
        "bus capacity": "bus capacity",
        "bus overcrowding": "bus overcrowding",
        "bus maintenance": "bus maintenance",
        "bus breakdown": "bus breakdown",
        "bus accident": "bus accident",
        "bus fire": "bus fire",
        "bus emergency": "bus emergency",
        "bus safety": "bus safety",
        "bus security": "bus security",
        "bus theft": "bus theft",
        "bus vandalism": "bus vandalism",
        "bus graffiti": "bus graffiti",
        "bus litter": "bus litter",
        "bus cleanliness": "bus cleanliness",
        "bus hygiene": "bus hygiene",
        "bus smell": "bus smell",
        "bus odor": "bus odor",
        "bus pest": "bus pest",
        "bus rat": "bus rat",
        "bus cockroach": "bus cockroach",
        "bus infestation": "bus infestation",
        "bus noise": "bus noise",
        "bus loud": "bus loud",
        "bus music": "bus music",
        "bus disturbance": "bus disturbance",
        "bus complaint": "bus complaint",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus enquiry": "bus enquiry",
        "bus information": "bus information",
        "bus help": "bus help",
        "bus support": "bus support",
        "bus contact": "bus contact",
        "bus staff": "bus staff",
        "bus driver behaviour": "bus driver behaviour",
        "bus reckless": "bus reckless",
        "bus rude": "bus rude",
        "bus aggressive": "bus aggressive",
        "bus dangerous": "bus dangerous",
        "bus speeding": "bus speeding",
        "bus running red light": "bus running red light",
        "bus illegal": "bus illegal",
        "bus by law": "bus by law",
        "bus zoning": "bus zoning",
        "bus land use": "bus land use",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general": "bus general",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information",
        "bus complaint about": "bus complaint about",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus building plan": "bus building plan",
        "bus zoning enquiry": "bus zoning enquiry",
        "bus staff complaint": "bus staff complaint",
        "bus service complaint": "bus service complaint",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information"
    }
# Enhanced synonym expansion: map common user terms to technical terms used in call types
    synonym_mappings = {
        # Prepaid meter synonyms
        "voucher": "token",
        "hasn't loaded": "token failed",
        "hasn't worked": "token failed",
        "didn't load": "token failed",
        "not loading": "token failed",
        "won't load": "token failed",
        "not accepted": "token rejected",
        "won't accept": "token rejected",
        "code not working": "token failed",
        "entered the code": "prepaid token",
        "add credit": "prepaid",
        "top up": "prepaid",
        "topup": "prepaid",
        "recharge": "prepaid",
        # Water-related synonyms
        "water pressure low": "low water pressure",
        "water pressure is low": "low water pressure",
        "weak water": "low water pressure",
        "trickling": "low water pressure",
        "slow flow": "low water pressure",
        "water comes and goes": "intermittent water supply",
        "water intermittent": "intermittent water supply",
        "water on and off": "intermittent water supply",
        "no water from taps": "no water",
        "dry taps": "no water",
        "water outage": "no water",
        # Electricity-related synonyms
        "power out": "no supply",
        "no power": "no supply",
        "electricity out": "no supply",
        "blackout": "no supply",
        "lights off": "no supply",
        "power outage": "no supply",
        # General synonyms
        "no change": "not working",
        "still shows": "not working",
        "broken": "damaged",
        "not working": "faulty",
        # Bollard and road infrastructure synonyms
        "bollard": "municipal bollard",
        "bollards": "municipal bollard",
        "damaged bollard": "municipal bollard repair",
        "broken bollard": "municipal bollard repair",
        "knocked over bollard": "municipal bollard repair",
        "fallen bollard": "municipal bollard repair",
        "bollard damaged": "municipal bollard repair",
        "bollard broken": "municipal bollard repair",
        "bollard needs repair": "municipal bollard repair",
        "bollard needs fixing": "municipal bollard repair",
        "bollard inspection": "municipal bollard repair",
        "municipal bollard": "municipal bollard repair",
        # Road and infrastructure terms
        "road barrier": "guardrail",
        "traffic barrier": "guardrail",
        "safety barrier": "guardrail",
        "road sign damaged": "damaged road sign",
        "traffic sign broken": "damaged road sign",
        "street sign": "road sign",
        # Pothole variations
        "hole in road": "pothole",
        "road hole": "pothole",
        "crack in road": "pothole",
        "road damage": "pothole",
        # Bus-related synonyms
        "metro bus": "metrobus",
        "metrobus": "metrobus",
        "bus stop": "bus stop",
        "bus route": "bus route",
        "bus card": "bus card",
        "bus driver": "bus driver",
        "bus seats": "bus seats",
        "bus dirty": "dirty bus",
        "bus is": "bus is",
        "bus are": "bus are",
        "bus late": "bus late",
        "bus not": "bus not running",
        "bus damaged": "bus damaged",
        "bus shelter": "bus shelter",
        "bus timetable": "bus timetable",
        "bus schedule": "bus schedule",
        "bus fare": "bus fare",
        "bus ticket": "bus ticket",
        "bus pass": "bus pass",
        "bus transfer": "bus transfer",
        "bus route change": "bus route change",
        "bus detour": "bus detour",
        "bus replacement": "bus replacement",
        "bus diversion": "bus diversion",
        "bus service": "bus service",
        "bus frequency": "bus frequency",
        "bus capacity": "bus capacity",
        "bus overcrowding": "bus overcrowding",
        "bus maintenance": "bus maintenance",
        "bus breakdown": "bus breakdown",
        "bus accident": "bus accident",
        "bus fire": "bus fire",
        "bus emergency": "bus emergency",
        "bus safety": "bus safety",
        "bus security": "bus security",
        "bus theft": "bus theft",
        "bus vandalism": "bus vandalism",
        "bus graffiti": "bus graffiti",
        "bus litter": "bus litter",
        "bus cleanliness": "bus cleanliness",
        "bus hygiene": "bus hygiene",
        "bus smell": "bus smell",
        "bus odor": "bus odor",
        "bus pest": "bus pest",
        "bus rat": "bus rat",
        "bus cockroach": "bus cockroach",
        "bus infestation": "bus infestation",
        "bus noise": "bus noise",
        "bus loud": "bus loud",
        "bus music": "bus music",
        "bus disturbance": "bus disturbance",
        "bus complaint": "bus complaint",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus enquiry": "bus enquiry",
        "bus information": "bus information",
        "bus help": "bus help",
        "bus support": "bus support",
        "bus contact": "bus contact",
        "bus staff": "bus staff",
        "bus driver behaviour": "bus driver behaviour",
        "bus reckless": "bus reckless",
        "bus rude": "bus rude",
        "bus aggressive": "bus aggressive",
        "bus dangerous": "bus dangerous",
        "bus speeding": "bus speeding",
        "bus running red light": "bus running red light",
        "bus illegal": "bus illegal",
        "bus by law": "bus by law",
        "bus zoning": "bus zoning",
        "bus land use": "bus land use",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general": "bus general",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information",
        "bus complaint about": "bus complaint about",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus building plan": "bus building plan",
        "bus zoning enquiry": "bus zoning enquiry",
        "bus staff complaint": "bus staff complaint",
        "bus service complaint": "bus service complaint",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information"
    }
# Enhanced synonym expansion: map common user terms to technical terms used in call types
    synonym_mappings = {
        # Prepaid meter synonyms
        "voucher": "token",
        "hasn't loaded": "token failed",
        "hasn't worked": "token failed",
        "didn't load": "token failed",
        "not loading": "token failed",
        "won't load": "token failed",
        "not accepted": "token rejected",
        "won't accept": "token rejected",
        "code not working": "token failed",
        "entered the code": "prepaid token",
        "add credit": "prepaid",
        "top up": "prepaid",
        "topup": "prepaid",
        "recharge": "prepaid",
        # Water-related synonyms
        "water pressure low": "low water pressure",
        "water pressure is low": "low water pressure",
        "weak water": "low water pressure",
        "trickling": "low water pressure",
        "slow flow": "low water pressure",
        "water comes and goes": "intermittent water supply",
        "water intermittent": "intermittent water supply",
        "water on and off": "intermittent water supply",
        "no water from taps": "no water",
        "dry taps": "no water",
        "water outage": "no water",
        # Electricity-related synonyms
        "power out": "no supply",
        "no power": "no supply",
        "electricity out": "no supply",
        "blackout": "no supply",
        "lights off": "no supply",
        "power outage": "no supply",
        # General synonyms
        "no change": "not working",
        "still shows": "not working",
        "broken": "damaged",
        "not working": "faulty",
        # Bollard and road infrastructure synonyms
        "bollard": "municipal bollard",
        "bollards": "municipal bollard",
        "damaged bollard": "municipal bollard repair",
        "broken bollard": "municipal bollard repair",
        "knocked over bollard": "municipal bollard repair",
        "fallen bollard": "municipal bollard repair",
        "bollard damaged": "municipal bollard repair",
        "bollard broken": "municipal bollard repair",
        "bollard needs repair": "municipal bollard repair",
        "bollard needs fixing": "municipal bollard repair",
        "bollard inspection": "municipal bollard repair",
        "municipal bollard": "municipal bollard repair",
        # Road and infrastructure terms
        "road barrier": "guardrail",
        "traffic barrier": "guardrail",
        "safety barrier": "guardrail",
        "road sign damaged": "damaged road sign",
        "traffic sign broken": "damaged road sign",
        "street sign": "road sign",
        # Pothole variations
        "hole in road": "pothole",
        "road hole": "pothole",
        "crack in road": "pothole",
        "road damage": "pothole",
        # Bus-related synonyms
        "metro bus": "metrobus",
        "metrobus": "metrobus",
        "bus stop": "bus stop",
        "bus route": "bus route",
        "bus card": "bus card",
        "bus driver": "bus driver",
        "bus seats": "bus seats",
        "bus dirty": "dirty bus",
        "bus is": "bus is",
        "bus are": "bus are",
        "bus late": "bus late",
        "bus not": "bus not running",
        "bus damaged": "bus damaged",
        "bus shelter": "bus shelter",
        "bus timetable": "bus timetable",
        "bus schedule": "bus schedule",
        "bus fare": "bus fare",
        "bus ticket": "bus ticket",
        "bus pass": "bus pass",
        "bus transfer": "bus transfer",
        "bus route change": "bus route change",
        "bus detour": "bus detour",
        "bus replacement": "bus replacement",
        "bus diversion": "bus diversion",
        "bus service": "bus service",
        "bus frequency": "bus frequency",
        "bus capacity": "bus capacity",
        "bus overcrowding": "bus overcrowding",
        "bus maintenance": "bus maintenance",
        "bus breakdown": "bus breakdown",
        "bus accident": "bus accident",
        "bus fire": "bus fire",
        "bus emergency": "bus emergency",
        "bus safety": "bus safety",
        "bus security": "bus security",
        "bus theft": "bus theft",
        "bus vandalism": "bus vandalism",
        "bus graffiti": "bus graffiti",
        "bus litter": "bus litter",
        "bus cleanliness": "bus cleanliness",
        "bus hygiene": "bus hygiene",
        "bus smell": "bus smell",
        "bus odor": "bus odor",
        "bus pest": "bus pest",
        "bus rat": "bus rat",
        "bus cockroach": "bus cockroach",
        "bus infestation": "bus infestation",
        "bus noise": "bus noise",
        "bus loud": "bus loud",
        "bus music": "bus music",
        "bus disturbance": "bus disturbance",
        "bus complaint": "bus complaint",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus enquiry": "bus enquiry",
        "bus information": "bus information",
        "bus help": "bus help",
        "bus support": "bus support",
        "bus contact": "bus contact",
        "bus staff": "bus staff",
        "bus driver behaviour": "bus driver behaviour",
        "bus reckless": "bus reckless",
        "bus rude": "bus rude",
        "bus aggressive": "bus aggressive",
        "bus dangerous": "bus dangerous",
        "bus speeding": "bus speeding",
        "bus running red light": "bus running red light",
        "bus illegal": "bus illegal",
        "bus by law": "bus by law",
        "bus zoning": "bus zoning",
        "bus land use": "bus land use",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general": "bus general",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information",
        "bus complaint about": "bus complaint about",
        "bus compliment": "bus compliment",
        "bus feedback": "bus feedback",
        "bus building plan": "bus building plan",
        "bus zoning enquiry": "bus zoning enquiry",
        "bus staff complaint": "bus staff complaint",
        "bus service complaint": "bus service complaint",
        "bus illegal construction": "bus illegal construction",
        "bus illegal building": "bus illegal building",
        "bus general enquiry": "bus general enquiry",
        "bus general information": "bus general information"
    }

    # Apply synonym expansion
    expanded_text = text_lower
    for user_term, technical_term in synonym_mappings.items():
        if user_term in expanded_text:
            expanded_text = expanded_text + " " + technical_term

    text_lower = expanded_text
    text_words = set(text_lower.split())

    # =============================================================================
    # ENHANCEMENT: Broader candidate search for better discoverability
    # When intent_bucket is uncertain or input is vague, search more broadly
    # =============================================================================
    input_length = len(user_text.split())
    is_vague_input_flag = input_length <= 3 or user_text.lower().strip() in ["water", "electricity", "power", "electric"]

    # Determine candidate pool size based on input clarity
    if is_vague_input_flag or not intent_bucket:
        # Vague input or no bucket - search more broadly
        candidate_pool_size = 50  # Increased from 25
        logger.info(f"Vague input detected, using broader candidate search (pool size: {candidate_pool_size})")
    elif input_length >= 15:
        # Long detailed input - can be more selective
        candidate_pool_size = 30
    else:
        # Normal input
        candidate_pool_size = 25

    # =============================================================================
    # TASK 1: CANDIDATE REDUCTION - Pre-filter before expensive scoring
    # =============================================================================
    call_types = reduce_candidates(
        intent_bucket=intent_bucket,
        problem_group=problem_group or (state.get("_problem_group") if state else None),
        conversation_history=history,
        all_call_types=ALL_CALL_TYPES_CACHE,
        top_k=candidate_pool_size  # Use dynamic pool size
    )

    # ENHANCEMENT: Broader fallback strategy for better discoverability
    if len(call_types) < 5:
        if intent_bucket:
            # First try the detected intent bucket
            call_types = get_call_types_by_intent(intent_bucket)

            # If still too few results, also check "general" bucket
            # Some call types (like bollards) might be in "general" even if detected as "roads"
            if len(call_types) < 5 and intent_bucket != "general":
                general_types = get_call_types_by_intent("general")
                # Combine but avoid duplicates
                existing_codes = {ct.get("call_type_code") for ct in call_types}
                for ct in general_types:
                    if ct.get("call_type_code") not in existing_codes:
                        call_types.append(ct)

            # ENHANCEMENT: If still too few, expand to related buckets
            if len(call_types) < 5:
                # Try related buckets (e.g., if water, also check general)
                related_buckets = {
                    "water": ["general"],
                    "electricity": ["general"],
                    "roads": ["general"],
                    "waste": ["general"],
                    "emergency": ["general"],
                    "transport": ["general"],
                    "health": ["general"],
                    "billing": ["general"],
                }
                if intent_bucket in related_buckets:
                    for related in related_buckets[intent_bucket]:
                        related_types = get_call_types_by_intent(related)
                        existing_codes = {ct.get("call_type_code") for ct in call_types}
                        for ct in related_types:
                            if ct.get("call_type_code") not in existing_codes:
                                call_types.append(ct)
        else:
            # No intent bucket - search all call types but prioritize by concept detection
            call_types = ALL_CALL_TYPES_CACHE[:100]  # Limit to top 100 for performance

    # =============================================================================
    # PHASE 2 (CRITICAL FIX): Semantic retrieval must expand candidates
    # -----------------------------------------------------------------------------
    # Previous implementation only used embeddings to score candidates that already
    # had keyword hits. That means semantic matching can never "rescue" cases with
    # zero keyword overlap (e.g., "my taps are dry").
    #
    # Here we retrieve top semantic matches and merge them into the candidate pool.
    # =============================================================================
    try:
        semantic_candidate_k = 30
        semantic_scope = call_types if intent_bucket else ALL_CALL_TYPES_CACHE
        # Build a fast lookup of call_type_code -> call type dict
        by_code = {str(ct.get("call_type_code")): ct for ct in semantic_scope if ct.get("call_type_code") is not None}
        semantic_matches = get_semantic_matches(corrected_context, top_k=semantic_candidate_k)
        existing_codes = {str(ct.get("call_type_code")) for ct in call_types if ct.get("call_type_code") is not None}
        for code, score in semantic_matches:
            # Ignore very low semantic matches to avoid polluting candidates
            if score < 0.45:
                continue
            if code in existing_codes:
                continue
            ct = by_code.get(code)
            if ct:
                call_types.append(ct)
                existing_codes.add(code)
    except Exception as e:
        logger.debug(f"Semantic retrieval candidate expansion failed: {e}")

    # =============================================================================
    # ENHANCEMENT: Enhanced repetition boost from conversation history
    # Keywords mentioned multiple times across turns increase confidence
    # Also track semantic consistency across conversation
    # =============================================================================
    keyword_repetition_count = {}
    semantic_consistency_boost = 0.0

    if history:
        history_text = " ".join(history).lower()
        combined_text = history_text + " " + text_lower

        # Track keyword repetition across entire conversation
        for ct in call_types:
            for kw in ct.get("keywords", []):
                kw_lower = kw.lower()
                # Count occurrences in full conversation context
                count = combined_text.count(kw_lower)
                if count > 1:
                    keyword_repetition_count[kw_lower] = count

        # ENHANCEMENT: Semantic consistency boost
        # If user consistently mentions same issue type across messages, boost confidence
        if len(history) >= 2:
            # Check if current message reinforces previous messages
            recent_keywords = set()
            for msg in history[-3:]:  # Last 3 messages
                recent_keywords.update(msg.lower().split())

            current_keywords = set(text_lower.split())
            overlap = recent_keywords.intersection(current_keywords)
            # If significant overlap (3+ shared meaningful words), boost confidence
            meaningful_overlap = [w for w in overlap if len(w) > 3]
            if len(meaningful_overlap) >= 3:
                semantic_consistency_boost = 0.08
                logger.info(f"Semantic consistency detected: {len(meaningful_overlap)} shared keywords")

    matches = []

    # =============================================================================
    # FIX 4: Disambiguate "illegal connection" correctly
    # Boost confidence for more specific matches (10001 BYPASSED WATER METER vs 10078 ILLEGAL CONN.)
    # When "bypass" or "meter" is mentioned, prefer 10001
    # Otherwise, let normal matching proceed (both are valid matches)
    # =============================================================================
    text_l = user_text.lower()
    boost_bypass_meter = False
    if "illegal" in text_l and "connection" in text_l:
        if "bypass" in text_l or "meter" in text_l:
            # User mentioned "bypass" or "meter" - boost 10001 (BYPASSED WATER METER)
            boost_bypass_meter = True
            logger.info("FIX 4: Detected 'illegal connection' with 'bypass'/'meter', will boost call type 10001")

    for ct in call_types:
        keywords = ct.get("keywords", [])
        negative_keywords = ct.get("negative_keywords", [])
        base_confidence = ct.get("confidence_weight", 0.7)
        min_confidence = ct.get("min_confidence_required", 0.75)

        # =============================================================================
        # TASK 3: STRENGTHENED NEGATIVE KEYWORD PENALTIES
        # Weighted by severity: exact phrase match > word match > category conflict
        # =============================================================================

        neg_keywords_found = []
        negative_penalty = 0.0

        for neg_kw in negative_keywords:
            neg_kw_lower = neg_kw.lower()
            if neg_kw_lower in text_lower:
                neg_keywords_found.append(neg_kw)
                # Graduated penalty: longer/more specific negative keywords = stronger signal
                if len(neg_kw.split()) >= 2:
                    negative_penalty += 0.25  # Multi-word negative = strong disqualifier
                else:
                    negative_penalty += 0.15  # Single word = moderate penalty

        # SOFTENED: Negative keywords reduce confidence but don't completely block
        # Old: 0.4 multiplier (60% penalty) was too harsh, making call types unreachable
        # New: 0.65 multiplier (35% penalty) - still significant but allows discovery
        if neg_keywords_found:
            # Graduated penalty based on number of negative keywords
            if len(neg_keywords_found) >= 2:
                negative_keyword_multiplier = 0.5  # Multiple negatives = stronger penalty
            else:
                negative_keyword_multiplier = 0.65  # Single negative = moderate penalty
        else:
            negative_keyword_multiplier = 1.0

        # HARD DISQUALIFY if 3+ negatives OR single penalty exceeds 0.5
        if len(neg_keywords_found) >= 3 or negative_penalty >= 0.5:
            continue

        # Score positive keywords with match strength tracking
        keyword_matches = 0
        matched_kws = []
        strong_matches = 0  # Track high-quality matches
        exact_phrase_matches = 0  # Track exact phrase matches (strongest signal)

        for kw in keywords:
            kw_lower = kw.lower()
            # Exact phrase match (strongest signal)
            if kw_lower in text_lower:
                keyword_matches += 1
                matched_kws.append(kw)
                # Multi-word exact matches are strong indicators
                if len(kw.split()) >= 2:
                    strong_matches += 1
                    exact_phrase_matches += 1
                else:
                    # Single word exact match
                    keyword_matches += 0.3  # Boost single word matches
            elif " " in kw_lower:
                # Multi-word partial match - check if all words are present
                kw_words = set(kw_lower.split())
                if kw_words.issubset(text_words):
                    keyword_matches += 0.7  # Increased from 0.5 for better matching
                    matched_kws.append(kw + " (partial)")
                    strong_matches += 0.5
            else:
                # Single word - check for word boundary matches (more precise)
                word_pattern = r'\b' + re.escape(kw_lower) + r'\b'
                if re.search(word_pattern, text_lower):
                    keyword_matches += 0.5  # Boost for word boundary matches
                    matched_kws.append(kw + " (word)")

        # =============================================================================
        # PHASE 2 (CRITICAL FIX): Allow semantic-only matches
        # -----------------------------------------------------------------------------
        # If we require keyword hits, embeddings can never help cases with no overlap.
        # We compute semantic_score later (Phase 2), but we must not bail out here.
        #
        # Strategy:
        # - If there are no keyword hits, we still allow the candidate through
        #   provided it is a strong semantic match.
        # =============================================================================
        allow_semantic_only = False
        semantic_score_precomputed = False
        if keyword_matches == 0:
            try:
                call_type_code_str = str(ct.get("call_type_code", ""))
                if call_type_code_str:
                    tmp_sem = get_semantic_score(
                        user_text=corrected_context,
                        call_type_code=call_type_code_str
                    )
                    # LOWERED: Allow semantic-only matches at 0.50 (was 0.60)
                    # This makes more call types discoverable even without keyword matches
                    if tmp_sem >= 0.50:
                        allow_semantic_only = True
                        semantic_score = tmp_sem  # reuse later; avoids recompute in common path
                        semantic_score_precomputed = True
            except Exception:
                pass
            if not allow_semantic_only:
                continue

        # =============================================================================
        # TASK 4: ENHANCED CONFIDENCE CALCULATION
        # Combines: keyword strength + repetition boost + contradiction penalty
        # =============================================================================

        keyword_ratio = keyword_matches / max(len(keywords), 1)

        # Boost for absolute match count (more matches = more confident)
        match_boost = min(0.3, keyword_matches * 0.1)

        # Boost for strong (multi-word) matches - indicates precise match
        strong_match_boost = min(0.20, strong_matches * 0.07)  # Increased boost

        # Extra boost for exact phrase matches (very strong signal)
        exact_phrase_boost = min(0.15, exact_phrase_matches * 0.1)

        # =============================================================================
        # PHASE 2: EMBEDDING-BASED SEMANTIC MATCHING
        # Get semantic similarity score from embeddings
        # =============================================================================
        # If semantic-only path already computed semantic_score above, keep it.
        semantic_score = semantic_score if semantic_score_precomputed else 0.0
        try:
            call_type_code_str = str(ct.get("call_type_code", ""))
            if call_type_code_str:
                if not semantic_score_precomputed:
                    semantic_score = get_semantic_score(
                        user_text=corrected_context,  # Use corrected context for semantic matching
                        call_type_code=call_type_code_str
                    )
        except Exception as e:
            logger.debug(f"Error computing semantic score for {ct.get('call_type_code')}: {e}")
            semantic_score = 0.0
        
        # Description match boost - enhanced for better semantic matching
        description_boost = 0
        issue_type_lower = ct.get("issue_type", "").lower()
        short_desc_lower = ct.get("short_description", "").lower()
        department_lower = ct.get("department", "").lower()

        # Exact match on issue_type or short_description (strongest)
        if issue_type_lower and issue_type_lower in text_lower:
            description_boost = 0.3  # Increased from 0.2
        elif short_desc_lower and short_desc_lower in text_lower:
            description_boost = 0.25  # Increased from 0.15
        # Partial match - check if key words from description are present
        elif short_desc_lower:
            desc_words = [w for w in short_desc_lower.split() if len(w) > 3]
            matched_desc_words = sum(1 for word in desc_words if word in text_lower)
            if matched_desc_words >= 2:  # At least 2 significant words match
                description_boost = 0.2
            elif matched_desc_words == 1:
                description_boost = 0.1

        # Department name match boost (e.g., "municipal bollard" matches "MUNICIPAL BOLLARD REPAIR")
        if department_lower:
            dept_words = [w for w in department_lower.split() if len(w) > 3]
            matched_dept_words = sum(1 for word in dept_words if word in text_lower)
            if matched_dept_words >= 2:
                description_boost += 0.15  # Additional boost for department match

        # ENHANCEMENT: Enhanced repetition boost from conversation history
        # Keywords mentioned multiple times across turns = user is consistent
        repetition_boost = 0.0
        for kw in matched_kws:
            kw_clean = kw.replace(" (partial)", "").replace(" (word)", "").lower()
            if kw_clean in keyword_repetition_count:
                # Stronger boost for repeated keywords
                count = keyword_repetition_count[kw_clean]
                repetition_boost += min(0.08, count * 0.03)  # Increased from 0.05/0.02
        repetition_boost = min(0.20, repetition_boost)  # Increased cap from 0.15

        # Add semantic consistency boost if applicable
        if semantic_consistency_boost > 0:
            repetition_boost += semantic_consistency_boost

        # Cross-department negative evidence
        cross_dept_penalty = calculate_negative_evidence_score(
            user_text,
            ct.get("short_description", ""),
            ct.get("issue_category", "")
        )

        # =============================================================================
        # PHASE 3: MULTI-SIGNAL FUSION - Calculate keyword score (normalized 0-1)
        # =============================================================================
        # Calculate keyword-based score with all boosts
        keyword_base = base_confidence * (keyword_ratio + match_boost + strong_match_boost + exact_phrase_boost + description_boost) * 1.4
        keyword_base += repetition_boost

        # FLOOR: Ensure keyword_base is never too low if we have keyword matches
        if keyword_matches > 0:
            min_keyword_score = 0.4
            if exact_phrase_matches > 0:
                min_keyword_score = 0.6
            elif strong_matches > 0:
                min_keyword_score = 0.5
            keyword_base = max(keyword_base, min_keyword_score)

        # Additional boost for high-quality matches
        if exact_phrase_matches > 0 and keyword_ratio > 0.3:
            keyword_base += 0.1

        # ENHANCEMENT: Better handling of first message vs. follow-up messages
        conversation_length = 0
        if state:
            conversation_length = len(state.get("conversationHistory", []))

        if conversation_length <= 1:
            word_count = len(user_text.split())
            if word_count >= 20:
                keyword_base += 0.20
            elif word_count >= 10:
                keyword_base += 0.15
            elif word_count >= 5:
                keyword_base += 0.08
        else:
            if len(user_text.split()) >= 3:
                keyword_base += 0.03

        # Normalize keyword score to 0-1 range
        keyword_score = min(1.0, max(0.0, keyword_base))

        # Check for exact match
        exact_match = exact_phrase_matches > 0 and keyword_ratio >= 0.8

        # TF-IDF score (using keyword_ratio as proxy for now - can be enhanced later)
        tfidf_score = min(1.0, keyword_ratio * 1.2)  # Simple proxy based on keyword coverage

        # =============================================================================
        # PHASE 3: MULTI-SIGNAL FUSION - Combine all signals
        # =============================================================================
        base_score = compute_final_score(
            keyword_score=keyword_score,
            semantic_score=semantic_score,
            tfidf_score=tfidf_score,
            exact_match=exact_match
        )

        # SOFTENED: Vague input penalty
        # Old: 0.5 penalty (50% reduction) was too harsh, making call types unreachable
        # New: Graduated penalty based on how vague the input is
        vague_penalty = 0.0
        input_is_vague = is_vague_input(user_text)
        if input_is_vague:
            # Graduated penalty: very short = more penalty, longer = less penalty
            word_count = len(user_text.split())
            if word_count <= 2:
                vague_penalty = 0.25  # Short vague inputs get moderate penalty
            else:
                vague_penalty = 0.15  # Longer vague inputs get lighter penalty
            logger.debug(f"Applied vague input penalty: -{vague_penalty:.2f}")

        # =============================================================================
        # FIX: DESCRIPTION WORD DISAMBIGUATION
        # Penalize call types when key discriminating words from their description
        # are NOT present in the user message. Boost when they ARE present.
        # Uses MULTIPLIERS to ensure penalties are effective regardless of base score.
        # =============================================================================
        description_disambiguation_multiplier = 1.0
        description_disambiguation_boost = 0.0

        # Key discriminating words that MUST be present for certain call types
        # If these words are in the description but NOT in user text, apply multiplier penalty
        discriminating_words = {
            "stolen": 0.3,    # "METER STOLEN" - multiply by 0.3 (70% penalty) if "stolen" not in text
            "damaged": 0.5,   # "DAMAGED METER" - multiply by 0.5 if "damaged" not in text
            "broken": 0.5,    # "METER BROKEN" - multiply by 0.5 if "broken" not in text
            "bees": 0.2,      # "BEES-METER BOX" - multiply by 0.2 if "bees" not in text
            "fire": 0.4,      # Fire-related - multiply by 0.4 if "fire" not in text
            "accident": 0.4,  # Accident-related - multiply by 0.4 if "accident" not in text
        }

        # Words that indicate prepaid/vending issues - boost these call types
        prepaid_indicator_words = ["voucher", "token", "credit", "load", "recharge", "top up", "topup", "code", "prepaid"]

        # Check description for discriminating words
        for disc_word, multiplier in discriminating_words.items():
            if disc_word in short_desc_lower and disc_word not in text_lower:
                # Key word in description but NOT in user text - apply multiplier penalty
                description_disambiguation_multiplier *= multiplier
                logger.info(f"Disambiguation multiplier: '{disc_word}' in desc '{short_desc_lower}' but not in user text, multiplier: {multiplier}")

        # Check if this is a prepaid-related call type and user mentioned prepaid indicators
        if any(ind in short_desc_lower for ind in ["prepaid", "voucher", "token", "vend"]):
            # This is a prepaid call type - boost if user mentioned prepaid indicators
            prepaid_matches = sum(1 for ind in prepaid_indicator_words if ind in text_lower)
            if prepaid_matches > 0:
                # Significant boost for prepaid match - up to 50% increase
                description_disambiguation_boost = min(0.5, prepaid_matches * 0.15)
                logger.info(f"Prepaid boost: {prepaid_matches} prepaid indicators found, boost: {description_disambiguation_boost}")

        total_penalty = negative_penalty + abs(cross_dept_penalty) + vague_penalty
        confidence = min(1.0, max(0.0, base_score - total_penalty + description_disambiguation_boost))

        # Apply disambiguation multiplier AFTER other calculations
        confidence = confidence * description_disambiguation_multiplier

        # Apply negative keyword multiplier (uses the softened values set earlier)
        # Old code had hardcoded 0.4 here which was too harsh
        if neg_keywords_found:
            confidence = confidence * negative_keyword_multiplier

        # SOFTENED: Cap for vague inputs raised to allow classification
        # Old: 0.5 cap was too harsh, making call types unreachable
        # New: 0.65 cap allows classification while still indicating uncertainty
        if input_is_vague:
            confidence = min(0.65, confidence)

        # TARGETED BOOST: Dirty bus hygiene issues (call type 25018)
        #
        # When the user clearly describes dirty seats on a bus, boost
        # the DIRTY BUS call type so it can reach the 0.3 classification threshold.
        # This is a specific, unambiguous case that should always classify.
        text_has_dirty_bus_seats = (
            "bus" in text_lower
            and any(tok in text_lower for tok in ["seat", "seats"])
            and any(tok in text_lower for tok in ["dirty", "filthy", "unclean", "smelly", "stained", "messy"])
        )
        is_dirty_bus_call_type = (
            str(ct.get("call_type_code")) == "25018"
            or "dirty bus" in short_desc_lower
        )
        if text_has_dirty_bus_seats and is_dirty_bus_call_type:
            # Significant boost (+0.25) to ensure this clear case classifies
            confidence = min(1.0, confidence + 0.25)
            logger.debug(f"Dirty bus seats boost applied, confidence now: {confidence}")

        # SAFEGUARD: Ensure confidence meets minimum threshold if we have keyword matches
        # If we matched keywords, we should have at least minimal confidence to be considered
        if keyword_matches > 0:
            # Ensure confidence meets minimum threshold for keyword matches
            min_confidence_for_match = CONFIDENCE_THRESHOLD_MIN  # 0.25
            if confidence < min_confidence_for_match:
                # More aggressive boost - ensure we always meet threshold for keyword matches
                # Use base_score (fused score) as reference
                boosted = max(min_confidence_for_match, base_score * 0.7)  # Use 70% of fused score
                # But ensure it's at least the threshold
                boosted = max(boosted, min_confidence_for_match)
                logger.info(f"Applied safeguard: boosted confidence from {confidence:.2f} to {boosted:.2f} to meet threshold (fused_score: {base_score:.2f}, keyword_matches: {keyword_matches})")
                confidence = boosted

        # FIX 4: Boost confidence for BYPASSED WATER METER (10001) when "bypass" or "meter" mentioned
        if boost_bypass_meter and str(ct.get("call_type_code")) == "10001":
            confidence = min(1.0, confidence + 0.15)  # Boost by 15% for more specific match
            logger.info(f"FIX 4: Boosted confidence for call type 10001 (BYPASSED WATER METER) to {confidence:.2f}")

        if confidence >= CONFIDENCE_THRESHOLD_MIN:
            # V5.1: Build decision trace for debugging
            decision_trace = {
                "keyword_score": round(keyword_score, 3),  # PHASE 3: Multi-signal fusion
                "semantic_score": round(semantic_score, 3),  # PHASE 2: Embedding score
                "tfidf_score": round(tfidf_score, 3),  # PHASE 3: TF-IDF score
                "fused_score": round(base_score, 3),  # PHASE 3: Combined score
                "concept_boosts": [],
                "negative_keyword_hits": neg_keywords_found,
                "confidence_weight": round(base_confidence, 3),
                "final_confidence": round(confidence, 3)
            }

            matches.append({
                "call_type_code": ct.get("call_type_code"),
                "short_description": ct.get("short_description"),
                "issue_type": ct.get("issue_type"),
                "department": ct.get("department"),
                "intent_bucket": ct.get("intent_bucket"),
                "issue_category": ct.get("issue_category"),
                "service_group": ct.get("service_group"),  # V5.1: Add service_group
                "confidence": round(confidence, 3),
                "min_confidence_required": min_confidence,
                "_matched_keywords": matched_kws,
                "_keyword_match_count": keyword_matches,
                "_strong_matches": strong_matches,
                "_total_keywords": len(keywords),
                "_negative_keywords_hit": neg_keywords_found,
                "_negative_penalty": round(total_penalty, 3),
                "_repetition_boost": round(repetition_boost, 3),
                "_decision_trace": decision_trace,  # V5.1: Add decision trace
            })

    # Sort by confidence descending
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    
    # =============================================================================
    # PHASE 5: CONFIDENCE CALIBRATION - Apply entropy-based calibration
    # =============================================================================
    if matches:
        calibrated_conf = calculate_calibrated_confidence(matches)
        # Update top match with calibrated confidence (but keep original for comparison)
        if matches:
            matches[0]["_original_confidence"] = matches[0]["confidence"]
            matches[0]["_calibrated_confidence"] = calibrated_conf
            # Use calibrated confidence for final decision
            matches[0]["confidence"] = calibrated_conf
            logger.debug(f"Confidence calibration: original={matches[0]['_original_confidence']:.3f}, calibrated={calibrated_conf:.3f}")

    # =============================================================================
    # FIX 2: Never return empty matches if we had keyword hits
    # Track if we had any keyword matches during iteration
    # =============================================================================
    had_keyword_hits = False
    best_keyword_match = None
    for ct in call_types:
        keywords = ct.get("keywords", [])
        if keywords:
            text_lower = user_text.lower()
            for kw in keywords:
                if kw.lower() in text_lower:
                    had_keyword_hits = True
                    if best_keyword_match is None:
                        best_keyword_match = {
                            "call_type_code": ct.get("call_type_code"),
                            "short_description": ct.get("short_description"),
                            "issue_type": ct.get("issue_type"),
                            "department": ct.get("department"),
                            "intent_bucket": ct.get("intent_bucket"),
                            "issue_category": ct.get("issue_category"),
                            "confidence": 0.45,  # Fallback confidence for keyword match
                            "_matched_keywords": [kw],
                            "_keyword_match_count": 1.0,
                            "_is_keyword_fallback": True
                        }
                    break
            if had_keyword_hits:
                break

    # If no matches but we had keyword hits, return the best keyword match
    if not matches and had_keyword_hits and best_keyword_match:
        logger.info(f"FIX 2: No matches found but keyword hits detected, returning fallback match: {best_keyword_match['call_type_code']}")
        matches = [best_keyword_match]

    # =============================================================================
    # SEMANTIC CONCEPT LAYER - Apply concept-based adjustments
    # This filters blocked departments and applies boosts/penalties
    # =============================================================================
    if concept_result.detected_concepts:
        matches = apply_concept_adjustments(matches, concept_result)

        # Store concept detection info in first match for debugging
        if matches:
            matches[0]["_detected_concepts"] = [
                cm.concept.name for cm in concept_result.detected_concepts
            ]
            # V5.1: Update decision trace with concept boosts
            if "_decision_trace" in matches[0]:
                matches[0]["_decision_trace"]["concept_boosts"] = [
                    cm.concept.name for cm in concept_result.detected_concepts
                ]

    # =============================================================================
    # TASK 5: AMBIGUITY GUARD
    # If top 2 matches are within threshold, flag as ambiguous
    # Caller should ask clarification question instead of classifying
    # =============================================================================
    AMBIGUITY_THRESHOLD = 0.05  # If top 2 within 5%, ambiguous

    if len(matches) >= 2:
        top_conf = matches[0]["confidence"]
        second_conf = matches[1]["confidence"]
        is_ambiguous = (top_conf - second_conf) <= AMBIGUITY_THRESHOLD

        # Mark all matches with ambiguity status
        for m in matches:
            m["_ambiguous"] = is_ambiguous
            if is_ambiguous:
                m["_ambiguity_candidates"] = [
                    matches[0]["short_description"],
                    matches[1]["short_description"]
                ]
    elif len(matches) == 1:
        matches[0]["_ambiguous"] = False

    return matches[:10]


__all__ = [
    "match_call_types_from_json",
    "detect_intent_bucket",
    "generate_ambiguity_clarification",
    "reduce_candidates",
    "detect_problem_group",
    "is_vague_input",
    "calculate_negative_evidence_score",
    "compute_final_score",
    "correct_typos",
    "calculate_calibrated_confidence",
    "CONFIDENCE_THRESHOLD_MIN",
    "CONFIDENCE_THRESHOLD_ASK",
    "CONFIDENCE_THRESHOLD_CONFIRM",
    "CONFIDENCE_THRESHOLD_LOCK",
    "PROBLEM_GROUPS",
    "NEGATIVE_EVIDENCE_SCORES",
    "get_call_type_description",
]


# generate_ambiguity_clarification
def generate_ambiguity_clarification(matches: List[Dict]) -> Optional[str]:
    """
    TASK 5: Generate a clarification question when top matches are ambiguous.
    Returns None if not ambiguous, otherwise returns a targeted question.

    Example: "I see this could be either a BURNT METER or METER DAMAGED issue.
              Is your meter physically broken, or did it catch fire/burn?"
    """
    if not matches or len(matches) < 2:
        return None

    if not matches[0].get("_ambiguous"):
        return None

    # Get the two competing call types
    first = matches[0].get("short_description", "")
    second = matches[1].get("short_description", "")

    # Generate a distinguishing question based on common confusion pairs
    # These are data-driven - no hardcoding of specific call types
    first_lower = first.lower()
    second_lower = second.lower()

    # Extract distinguishing keywords from each
    first_words = set(first_lower.split()) - {"the", "a", "an", "of", "on", "in", "for"}
    second_words = set(second_lower.split()) - {"the", "a", "an", "of", "on", "in", "for"}

    unique_first = first_words - second_words
    unique_second = second_words - first_words

    # Build a clarifying question
    if unique_first and unique_second:
        return (
            f"I need to clarify - is this about {' '.join(unique_first)} "
            f"or {' '.join(unique_second)}? "
            f"(Options: '{first}' vs '{second}')"
        )
    else:
        # Fallback: just present the options
        return (
            f"I found two similar issues: '{first}' and '{second}'. "
            f"Which one best describes your problem?"
        )


# detect_intent_bucket
def detect_intent_bucket(user_text: str) -> Optional[str]:
    """
    Detect the intent bucket (department category) from user text.
    This is the TENTATIVE classification before we have a specific call type.

    Available buckets (from JSON data - 612 call types):
    - water: Joburg Water (leaks, bursts, sewage, meters, pressure)
    - electricity: City Power (outages, street lights, prepaid, cables)
    - roads: JRA (potholes, traffic signals, signs, bridges, pavements)
    - waste: Pikitup (bins, collection, illegal dumping, recycling)
    - emergency: Fire & EMS (fires, accidents, rescue, medical)
    - transport: MetroBus & Rea Vaya (buses, routes, stops, cards)
    - health: Environmental Health (food safety, pests, noise, pollution)
    - billing: Revenue (accounts, statements, payments, rates)
    - general: General Contact & Complaints (complaints, compliments, enquiries)

    Returns: water, electricity, roads, waste, emergency, transport, health, billing, general or None
    """
    text_lower = user_text.lower()

    # Intent bucket keyword maps - expanded for all 9 departments
    # Keywords are weighted: primary keywords (strong indicators) vs secondary (weaker)
    bucket_keywords = {
        "water": {
            # Added single word "water" as secondary to match vague inputs
            "primary": ["water leak", "water problem", "burst pipe", "sewer", "sewage", "no water", "joburg water",
                       "water meter", "water pressure", "water cut", "taps dry", "water supply", "wrong with water",
                       "something wrong with water", "illegal connection", "illegal water connection", "bypass meter",
                       "water connection bypass", "illegal conn", "connection bypass"],
            "secondary": ["water", "pipe", "tap", "drain", "geyser", "flooding", "pressure", "manhole", "blockage",
                         "hydrant", "valve", "water connection", "connection", "ablution", "amanzi", "meter"]
        },
        "electricity": {
            "primary": ["electricity", "power outage", "no power", "city power", "street light", "prepaid meter",
                       "electric", "power cable", "electrical", "electricity meter", "voucher", "token not loading",
                       "units not loading", "meter not accepting", "prepaid voucher", "electricity voucher",
                       "bought units", "purchased units", "electricity token", "meter code"],
            "secondary": ["power", "lights", "outage", "blackout", "dark", "cable", "pole", "prepaid", "sparks",
                         "ugesi", "voltage", "substation", "meter box", "load shedding", "electrocution", "flickering",
                         "surge", "phase", "token", "units", "credit", "recharge"]
        },
        "roads": {
            "primary": ["pothole", "traffic light", "traffic signal", "road damage", "jra", "road marking",
                       "guard rail", "guardrail", "bridge crack", "bridge damage", "municipal bollard",
                       "bollard repair", "damaged bollard", "broken bollard", "bollard damaged"],
            "secondary": ["road", "traffic", "sign", "pavement", "bridge", "sidewalk", "kerb", "gravel", "tar",
                         "speed bump", "barrier", "footway", "trench", "storm water", "culvert", "bollard",
                         "bollards", "knocked over", "fallen", "inspection", "repair"]
        },
        "waste": {
            "primary": ["bin not collected", "refuse", "illegal dumping", "pikitup", "garbage collection", "rubbish",
                       "dead animal", "dead dog", "dead cat", "carcass", "roadkill", "animal carcass"],
            "secondary": ["garbage", "waste", "trash", "bin", "collection", "dump", "recycling", "litter",
                         "bulk container", "rubble", "branches"]
        },
        "emergency": {
            "primary": ["fire", "burning", "smoke", "ambulance", "rescue", "trapped", "accident", "ems",
                       "gas leak", "gas leaking", "smell gas", "smell of gas", "explosion", "wildfire", "grassfire",
                       "grass fire", "veld fire", "bush fire", "hazardous", "chemical spill", "toxic",
                       "help urgently", "urgent help", "emergency"],
            "secondary": ["urgent", "crime", "vehicle fire", "danger", "life threatening"]
        },
        "transport": {
            "primary": ["metrobus", "metro bus", "rea vaya", "reavaya", "bus stop", "bus route", "bus late",
                       "bus card", "bus driver", "dirty bus", "bus seats", "bus dirty", "filthy bus",
                       "unclean bus", "bus is dirty", "seats are dirty"],
            "secondary": ["bus", "taxi", "transport", "route", "fare", "driver", "passenger", "destination", "trip", "tag"]
        },
        "health": {
            "primary": ["rats ", " rat ", "cockroach", "pest control", "food poisoning", "noise complaint",
                       "environmental health", "rodent infestation", "food safety", "pest infestation"],
            "secondary": ["health", "pest", "mouse", "noise", "pollution", "smell", "odor", "hygiene",
                         "restaurant", "vendor", "sanitation", "air quality", "illness", "overcrowding", "unhygienic", "stagnant"]
        },
        "billing": {
            "primary": ["my bill", "my account", "my statement", "rates query", "payment query", "refund",
                       "consumption enquiry", "consumption query", "usage query", "pensioner rebate", "account balance",
                       "tariff enquiry", "rates too high", "high rates", "property rates", "my rates",
                       "water consumption", "electricity consumption", "high usage", "bill query"],
            "secondary": ["bill", "account", "statement", "payment", "tariff", "charge", "credit", "debit",
                         "revenue", "balance", "arrears", "deposit", "pensioner", "rebate", "valuation", "clearance", "debt", "rates"]
        },
        "general": {
            "primary": ["complaint about", "compliment", "feedback", "building plan", "zoning enquiry",
                       "staff complaint", "service complaint", "illegal construction", "illegal building",
                       "general enquiry", "general information"],
            "secondary": ["complaint", "query", "enquiry", "information", "support", "contact", "staff",
                         "zoning", "land use", "by-law", "illegal", "need help", "help me"]
        },
    }

    # =============================================================================
    # SEMANTIC CONCEPT LAYER - Use concepts to guide intent detection
    # Concepts can strongly indicate or block certain departments
    # =============================================================================
    concept_result = detect_concepts(user_text)

    # If concepts uniquely constrain to one department, use that
    if concept_result.allowed_departments:
        allowed = concept_result.allowed_departments - concept_result.blocked_departments
        if len(allowed) == 1:
            concept_bucket = list(allowed)[0]
            logger.info(f"Concept layer determined intent_bucket: {concept_bucket}")
            return concept_bucket

    # Score with weighting: primary keywords = 3 points, secondary = 1 point
    scores = {}
    for bucket, kw_dict in bucket_keywords.items():
        score = 0
        # Check primary keywords first (stronger signal)
        for kw in kw_dict["primary"]:
            if kw in text_lower:
                score += 3
        # Check secondary keywords
        for kw in kw_dict["secondary"]:
            if kw in text_lower:
                score += 1
        if score > 0:
            scores[bucket] = score

    # Apply concept-based adjustments to scores
    # Boost allowed departments, heavily penalize blocked ones
    if concept_result.allowed_departments:
        for bucket in concept_result.allowed_departments:
            if bucket in scores:
                scores[bucket] += 5  # Strong boost for concept-allowed
            elif bucket not in concept_result.blocked_departments:
                scores[bucket] = 2  # Small baseline for allowed but no keywords

    for bucket in concept_result.blocked_departments:
        if bucket in scores:
            scores[bucket] = max(0, scores[bucket] - 10)  # Heavy penalty
            if scores[bucket] == 0:
                del scores[bucket]

    if not scores:
        return None

    # Return bucket with highest score
    best_bucket = max(scores, key=scores.get)
    return best_bucket

def get_call_type_description(call_type_code: int) -> str:
    """
    Get the description for a given call type code.
    
    Args:
        call_type_code: The call type code to get the description for
    
    Returns:
        The description of the call type, or a default message if not found
    """
    # Load the call types
    from src.utils.data_loader import load_all_json_call_types
    
    call_types = load_all_json_call_types()
    
    # Find the matching call type
    for call_type in call_types:
        if str(call_type.get("call_type_code")) == str(call_type_code):
            return call_type.get("short_description", f"Call type {call_type_code}")
    
    return f"Unknown call type: {call_type_code}"

