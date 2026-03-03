"""
Classification module for CSD Chatbot.

Contains:
- classifier_service: Silent classification layer
- semantic_concepts: Semantic concept detection for department gating
"""

from src.classification.classifier_service import (
    ClassifierService,
    classifier_service,
    classify_issue,
)

__all__ = [
    "ClassifierService",
    "classifier_service",
    "classify_issue",
]
