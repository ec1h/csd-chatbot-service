"""
Domain Detector
===============
Detects domain/department/intent from user input for multi-domain chatbots.
"""

from typing import Optional, List
import re

# Common department/domain keywords
DOMAIN_KEYWORDS = {
    "water": ["water", "pipe", "leak", "burst", "sewer", "drain", "plumbing"],
    "electricity": ["electricity", "power", "outage", "blackout", "lights", "electrical"],
    "roads": ["road", "street", "pothole", "pavement", "tar", "roadwork"],
    "refuse": ["refuse", "garbage", "trash", "waste", "bin", "collection", "rubbish"],
    "parks": ["park", "garden", "playground", "trees", "grass", "recreation"],
    "housing": ["housing", "apartment", "flat", "rent", "accommodation"],
    "billing": ["bill", "invoice", "payment", "account", "statement", "charge"],
    "general": ["help", "info", "information", "query", "question"],
}


def is_domain_only_input(user_message: str) -> bool:
    """
    Check if the input is ONLY a domain/department name without problem description.
    
    Examples:
    - "water" -> True
    - "electricity" -> True  
    - "water leak" -> False (has problem)
    - "my lights are off" -> False (has problem)
    """
    user_message = user_message.lower().strip()
    
    # Single word domain
    if user_message in DOMAIN_KEYWORDS:
        return True
    
    # Check if it's only domain keywords without descriptive words
    words = user_message.split()
    if len(words) <= 2:
        for domain in DOMAIN_KEYWORDS:
            if domain in user_message:
                # Check if there are problem-describing words
                problem_words = ["leak", "broken", "not working", "issue", "problem", 
                               "help", "need", "want", "can't", "won't", "doesn't"]
                if not any(word in user_message for word in problem_words):
                    return True
    
    return False


def detect_domain(user_message: str) -> Optional[str]:
    """
    Detect the domain/department from user input.
    
    Returns:
    - Domain name (e.g., "water", "electricity")
    - None if no clear domain detected
    """
    user_message = user_message.lower()
    
    # Score each domain by keyword matches
    domain_scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in user_message)
        if score > 0:
            domain_scores[domain] = score
    
    # Return domain with highest score
    if domain_scores:
        return max(domain_scores, key=domain_scores.get)
    
    return None


def detect_topic_switch(
    current_domain: Optional[str],
    new_message: str,
    conversation_history: List[str] = None
) -> bool:
    """
    Detect if the user is switching to a different topic/domain.
    
    Args:
        current_domain: The current conversation domain
        new_message: The new user message
        conversation_history: Previous messages for context
        
    Returns:
        True if topic switch detected
    """
    if not current_domain:
        return False
    
    detected_domain = detect_domain(new_message)
    
    # If we detect a different domain explicitly mentioned
    if detected_domain and detected_domain != current_domain:
        # Check for explicit topic switch phrases
        switch_phrases = [
            "actually", "wait", "no", "instead", "change",
            "different", "another", "other", "not about"
        ]
        if any(phrase in new_message.lower() for phrase in switch_phrases):
            return True
            
        # Strong signal: new domain mentioned without connection to current
        return True
    
    return False


def generate_domain_clarification(detected_domain: Optional[str] = None) -> str:
    """
    Generate a clarification question when only domain is mentioned.
    
    Args:
        detected_domain: The detected domain/department
        
    Returns:
        A clarification question
    """
    if detected_domain:
        domain_prompts = {
            "water": "What water-related issue are you experiencing? For example, a leak, no water supply, or sewage problem?",
            "electricity": "What electricity issue are you experiencing? For example, a power outage, faulty streetlight, or electrical fault?",
            "roads": "What road-related issue are you reporting? For example, a pothole, damaged road surface, or traffic sign problem?",
            "refuse": "What refuse-related issue do you have? For example, missed collection, damaged bin, or illegal dumping?",
            "parks": "What parks-related issue are you reporting? For example, damaged equipment, maintenance needed, or vandalism?",
            "housing": "What housing issue are you experiencing? For example, maintenance request, tenant query, or application status?",
            "billing": "What billing issue do you have? For example, incorrect charge, payment query, or account statement?",
        }
        
        return domain_prompts.get(
            detected_domain,
            f"I understand you're asking about {detected_domain}. Could you please provide more details about the specific issue you're experiencing?"
        )
    
    # No domain detected
    return (
        "I'd be happy to help! Could you please describe the issue you're experiencing? "
        "For example, you can report issues related to water, electricity, roads, refuse collection, parks, or other municipal services."
    )
