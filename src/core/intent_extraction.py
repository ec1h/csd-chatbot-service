"""
Intent Extraction - Non-Classifying Layer
=========================================

This module provides a **non-classifying** intent understanding layer.

Responsibilities:
- Call the LLM via the existing DSPy infrastructure
- Extract a lightweight, semantic view of the user's issue
- NEVER return a department or call type
- Surface what information is missing to safely classify later

This layer is deliberately conservative and schema-validated so that
downstream logic can make safe decisions about when to block or allow
classification.
"""

from __future__ import annotations

import logging
from typing import List

from pydantic import BaseModel, Field, ValidationError, confloat

from src.core.dspy_pipeline import context_analyzer


logger = logging.getLogger(__name__)


class IntentExtractionResult(BaseModel):
    """
    Schema-validated output of the intent extraction layer.

    NOTE: This intentionally DOES NOT contain:
    - department
    - call type
    - call type code
    or any other routing / classification artefacts.
    """

    issue_summary: str = Field(
        ...,
        description="Short natural-language summary of the issue (no departments or codes).",
        min_length=1,
        max_length=512,
    )
    confidence: confloat(ge=0.0, le=1.0) = Field(
        ...,
        description="LLM confidence that it correctly understood the user's problem (0.0–1.0).",
    )
    detected_assets: List[str] = Field(
        default_factory=list,
        description="Physical or logical assets mentioned (e.g. 'seats', 'street light').",
    )
    possible_contexts: List[str] = Field(
        default_factory=list,
        description="High-level contexts the issue might relate to (e.g. 'transport', 'public_building').",
    )
    missing_slots: List[str] = Field(
        default_factory=list,
        description="Semantic 'slots' that are still missing (e.g. 'facility_type', 'location_type').",
    )


class IntentExtractionError(RuntimeError):
    """Raised when intent extraction fails in a non-recoverable way."""


def _map_confidence_label_to_score(label: str) -> float:
    """Map DSPy `confidence` label (high/medium/low) to a numeric score."""
    label = (label or "").strip().lower()
    if label == "high":
        return 0.9
    if label == "medium":
        return 0.6
    if label == "low":
        return 0.3
    return 0.0


def _detect_assets_from_text(text: str) -> List[str]:
    """
    Lightweight heuristic asset detection.

    This deliberately stays generic and does NOT infer departments or call types.
    """
    text_l = text.lower()
    assets: List[str] = []

    # Seats / benches (key example from requirements)
    if any(tok in text_l for tok in ["seat", "seats", "bench", "benches"]):
        assets.append("seats")

    # Basic transport-related surfaces
    if any(tok in text_l for tok in ["bus", "taxi", "train", "coach", "minibus"]):
        assets.append("vehicle_interior")

    # Public building hints
    if any(tok in text_l for tok in ["clinic", "hospital", "waiting room", "hall", "library"]):
        assets.append("indoor_public_area")

    # Parks / outdoor seating
    if any(tok in text_l for tok in ["park", "playground", "bench in the park"]):
        assets.append("outdoor_public_area")

    # Deduplicate while preserving order
    seen = set()
    ordered_assets: List[str] = []
    for a in assets:
        if a not in seen:
            seen.add(a)
            ordered_assets.append(a)
    return ordered_assets


def _infer_possible_contexts(text: str) -> List[str]:
    """Infer coarse-grained possible contexts from raw text only."""
    text_l = text.lower()
    contexts: List[str] = []

    if any(tok in text_l for tok in ["bus", "taxi", "minibus", "coach", "driver"]):
        contexts.append("transport")
    if any(tok in text_l for tok in ["clinic", "hospital", "ward", "waiting room"]):
        contexts.append("public_building")
    if any(tok in text_l for tok in ["park", "playground", "bench", "benches"]):
        contexts.append("park")
    if any(tok in text_l for tok in ["mall", "shopping centre", "shopping center"]):
        contexts.append("commercial_area")

    # If we saw nothing specific, leave it empty – downstream logic
    # will treat the lack of context as additional uncertainty.
    seen = set()
    ordered_contexts: List[str] = []
    for c in contexts:
        if c not in seen:
            seen.add(c)
            ordered_contexts.append(c)
    return ordered_contexts


def _infer_missing_slots(issue_summary: str, detected_assets: List[str], possible_contexts: List[str]) -> List[str]:
    """
    Decide which semantic slots are still missing.

    This is intentionally conservative and focused on clearly ambiguous
    cases like "the seats are dirty", where we don't yet know:
    - what kind of facility these seats belong to
    - what type of location the user is in
    """
    issue_l = issue_summary.lower()
    missing: List[str] = []

    # Seats cleanliness ambiguity:
    # - we know *something* about seats
    # - but we haven't tied it to a facility or location type yet
    if "seats" in detected_assets or any(tok in issue_l for tok in ["seat", "seats", "bench", "benches"]):
        if not any(ctx in possible_contexts for ctx in ["transport", "public_building", "park"]):
            missing.append("facility_type")
            missing.append("location_type")

    # Additional missing-slot rules can be added here later in a guarded way.

    # Deduplicate while preserving order
    seen = set()
    ordered_missing: List[str] = []
    for m in missing:
        if m not in seen:
            seen.add(m)
            ordered_missing.append(m)
    return ordered_missing


def extract_intent(user_text: str) -> IntentExtractionResult:
    """
    Extract a **non-classifying** semantic intent representation for a user message.

    Failure behaviour:
    - If the LLM or DSPy stack fails, we log and fall back to a minimal,
      schema-valid result that does NOT block existing classification logic.
    - Callers that want to *gate* classification MUST explicitly check
      `missing_slots` and `confidence` and remain conservative.
    """
    raw_issue = user_text.strip()
    if not raw_issue:
        # Degenerate input – return a low-confidence, no-slots result
        return IntentExtractionResult(
            issue_summary="",
            confidence=0.0,
            detected_assets=[],
            possible_contexts=[],
            missing_slots=[],
        )

    try:
        # Use the existing wrapped DSPy predictor (with circuit breaker)
        # to understand the context of the story / brain dump.
        ctx = context_analyzer(user_story=raw_issue)

        # Some DSPy wrappers may return slightly different shapes; be defensive.
        extracted_issue = getattr(ctx, "extracted_issue", None) or raw_issue
        confidence_label = getattr(ctx, "confidence", "") or ""

        numeric_conf = _map_confidence_label_to_score(str(confidence_label))

        detected_assets = _detect_assets_from_text(raw_issue)
        possible_contexts = _infer_possible_contexts(raw_issue)
        missing_slots = _infer_missing_slots(extracted_issue, detected_assets, possible_contexts)

        result = IntentExtractionResult(
            issue_summary=extracted_issue.strip()[:512] or raw_issue[:512],
            confidence=numeric_conf,
            detected_assets=detected_assets,
            possible_contexts=possible_contexts,
            missing_slots=missing_slots,
        )
        return result

    except Exception as e:
        # Defensive: never let intent extraction break the main flow.
        logger.warning("Intent extraction failed, falling back to minimal intent: %s", e)

        try:
            # Ensure we still return a schema-valid object
            return IntentExtractionResult(
                issue_summary=raw_issue[:512],
                confidence=0.0,
                detected_assets=_detect_assets_from_text(raw_issue),
                possible_contexts=_infer_possible_contexts(raw_issue),
                missing_slots=[],
            )
        except ValidationError as ve:
            # If even this fails, raise a dedicated error so callers can opt to ignore it.
            logger.error("IntentExtractionResult validation failed: %s", ve)
            raise IntentExtractionError("Failed to build IntentExtractionResult") from ve


__all__ = ["IntentExtractionResult", "IntentExtractionError", "extract_intent"]

