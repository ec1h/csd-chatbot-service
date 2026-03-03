"""
Classifier Service - Silent Classification Layer
==================================================
This is the ONLY place where classification happens.
Rules:
- No logging to user
- No side effects
- No state changes
- No frontend flags
- Returns classification results only
"""

from typing import Dict, Optional, List, Callable
import logging

logger = logging.getLogger(__name__)


class ClassifierService:
    """
    Classification service using dependency injection to avoid circular dependencies.
    
    The service accepts classification functions via set_classifiers() after initialization,
    allowing the pipeline to be configured during app startup.
    """
    
    def __init__(self):
        self._match_call_types_from_json: Optional[Callable] = None
        self._detect_intent_bucket: Optional[Callable] = None
    
    def set_classifiers(
        self,
        match_call_types_from_json: Callable,
        detect_intent_bucket: Callable
    ) -> None:
        """
        Set classification functions after initialization to avoid circular imports.
        
        Args:
            match_call_types_from_json: Function that matches user text to call types
            detect_intent_bucket: Function that detects intent bucket from text
        """
        self._match_call_types_from_json = match_call_types_from_json
        self._detect_intent_bucket = detect_intent_bucket
    
    def classify(self, text: str, conversation_history: Optional[List[str]] = None, top_n: int = 5) -> Dict:
        """
        Classify an issue from user text.
        
        NEW BEHAVIOR: Returns top-N candidates, not just the best match.
        This enables all call types to be discoverable through clarification.
        
        Returns:
        {
            "issue_label": str | None,  # Best match
            "call_type_code": int | None,  # Best match
            "confidence": float,  # Best match confidence
            "candidates": List[Dict],  # Top-N candidates
            "intent_bucket": str | None,  # Detected domain
        }
        
        Rules:
        - No logging to user
        - No side effects
        - No state changes
        - No frontend flags
        """
        if not self._match_call_types_from_json:
            raise RuntimeError("Classification functions not initialized. Call set_classifiers() first.")
        
        # Detect intent bucket first
        intent_bucket = None
        if self._detect_intent_bucket:
            intent_bucket = self._detect_intent_bucket(text)
        
        # Match call types
        matches = self._match_call_types_from_json(
            user_text=text,
            intent_bucket=intent_bucket,
            conversation_history=conversation_history or []
        )
        
        if not matches:
            return {
                "issue_label": None,
                "call_type_code": None,
                "confidence": 0.0,
                "candidates": [],
                "intent_bucket": intent_bucket,
            }
        
        # Get top N candidates
        top_candidates = matches[:top_n]
        
        # Get best match
        best_match = matches[0]
        
        return {
            "issue_label": best_match.get("short_description"),
            "call_type_code": best_match.get("call_type_code"),
            "confidence": best_match.get("confidence", 0.0),
            "candidates": top_candidates,  # NEW: Top-N candidates
            "intent_bucket": intent_bucket,  # NEW: Domain
        }


# Create singleton instance
classifier_service = ClassifierService()


# Backwards-compatible function interface
def classify_issue(text: str, conversation_history: Optional[List[str]] = None, top_n: int = 5) -> Dict:
    """
    Backwards-compatible function interface for classify_issue.
    
    This maintains compatibility with existing code that imports classify_issue directly.
    
    NEW: Now returns top-N candidates to enable all call types to be discoverable.
    """
    return classifier_service.classify(text, conversation_history, top_n)
