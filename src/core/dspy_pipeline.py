"""
DSPy pipeline configuration and helpers for the CSD Chatbot.

This module centralizes:
- DSPy language model configuration (Azure OpenAI backend)
- Signature and module definitions
- Construction of the main classification pipeline
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Literal

import dspy

from src.config import settings
from src.core.circuit_breaker import CircuitBreaker


logger = logging.getLogger(__name__)

# Circuit breaker for Azure OpenAI calls
azure_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30)


_lm: Optional[dspy.LM] = None


_configured = False


def _configure_lm() -> dspy.LM:
    """
    Configure the DSPy language model using Azure OpenAI settings.

    This mirrors the original `lm = dspy.LM(...)` and `dspy.configure(...)`
    initialization that previously lived in `app.py`.
    """
    global _lm, _configured
    if _lm is None:
        _lm = dspy.LM(
            f"azure/{settings.AZURE_OPENAI_DEPLOYMENT}",
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_base=settings.AZURE_OPENAI_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    if not _configured:
        try:
            dspy.configure(lm=_lm)
            _configured = True
        except RuntimeError as e:
            # If already configured in another context, that's okay
            if "can only be called from the same async task" not in str(e):
                raise
            logger.warning("DSPy already configured in another context, continuing...")
    return _lm


class RouteDecision(dspy.Signature):
    """Given a query and the top-5 for water & electricity, decide whether to auto-pick or ask user."""

    user_query: str = dspy.InputField()
    water_top5_json: str = dspy.InputField()  # JSON list: [{"code": "...", "desc": "..."}]
    electricity_top5_json: str = dspy.InputField()  # JSON list: [{"code": "...", "desc": "..."}]
    decision: Literal["auto_water", "auto_electricity", "ask_user"] = dspy.OutputField(
        desc="Return exactly one of: auto_water, auto_electricity, ask_user"
    )
    rationale: str = dspy.OutputField(
        desc="Short reason for the decision (for logging / debugging)."
    )


class UnderstandContext(dspy.Signature):
    """
    Subset of the long prompt from app.py retained for behavior compatibility.

    FEW-SHOT BEHAVIOUR EXAMPLES (guidance for the model):

    1) Dirty bus seats (transport interior hygiene)
       - user_story: "The bus seats are dirty and smell bad on my Metrobus this morning."
       - is_municipal: "no"        # vehicle interior, not pipe/cable infrastructure
       - context_type: "vehicle"
       - extracted_issue: "dirty, unhygienic seats inside a bus"
       - confidence: "high"

    2) Street light not working (municipal electrical asset)
       - user_story: "The street light outside my house has been off for three nights."
       - is_municipal: "yes"
       - context_type: ""          # leave empty when municipal
       - extracted_issue: "street light outside house not working"
       - confidence: "high"

    3) Vague category only
       - user_story: "electricity"
       - is_municipal: "yes"
       - context_type: ""          # still municipal, but not enough detail
       - extracted_issue: "electricity problem (details not provided)"
       - confidence: "low"

    4) Seats in a waiting room (public building)
       - user_story: "The chairs in the clinic waiting room are filthy and stained."
       - is_municipal: "no"
       - context_type: "public_building"
       - extracted_issue: "dirty, unhygienic seats in a clinic waiting room"
       - confidence: "high"

    The model MUST:
    - Focus on describing the issue in neutral language
    - Avoid naming departments, call types or codes
    - Prefer HIGH confidence only when the core issue is very clear
    """

    user_story: str = dspy.InputField()
    is_municipal: Literal["yes", "no"] = dspy.OutputField(
        desc="Is this about municipal water/electricity infrastructure? Answer 'yes' or 'no'"
    )
    context_type: str = dspy.OutputField(
        desc="If non-municipal, what is it? (vehicle, appliance, device, purchase, indoor_private). If municipal, leave empty."
    )
    extracted_issue: str = dspy.OutputField(
        desc="The core issue extracted from the story in simple terms (e.g., 'water leak in street', 'no power in area')"
    )
    confidence: Literal["high", "medium", "low"] = dspy.OutputField(
        desc="How confident are you in this classification?"
    )


class ClassifyCategory(dspy.Signature):
    """High-level classification into water/electricity/unknown."""

    user_query: str = dspy.InputField()
    category: Literal["water", "electricity", "unknown"] = dspy.OutputField(
        desc="Return exactly one of: water, electricity, unknown"
    )


class GenerateClarifyingQuestion(dspy.Signature):
    """Generate a short, contextual clarifying question about the PROBLEM only.
    Do NOT ask for location, address, street, or where. We ask for location later.
    Only ask about what's wrong, how bad, which part, etc."""

    user_message: str = dspy.InputField(desc="What the user said about their problem")
    service_category: str = dspy.InputField(desc="The detected category: water, electricity, roads, etc.")
    clarifying_question: str = dspy.OutputField(
        desc="A short follow-up question (1-2 sentences) about the problem only. Never ask for location or address."
    )


class RankTop5(dspy.Signature):
    """Rank candidate call types and return the top 5."""

    user_query: str = dspy.InputField()
    candidates_json: str = dspy.InputField()
    top5: str = dspy.OutputField(
        desc="Return a Python list (max 5) of dicts with keys 'code' and 'desc' only."
    )


class CallTypePipeline(dspy.Module):
    """
    Multi-stage pipeline for:
    - Category classification
    - Top-5 candidate ranking
    - Routing decision (auto-select vs ask user)
    """

    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(ClassifyCategory)
        self.rank = dspy.Predict(RankTop5)
        self.route = dspy.Predict(RouteDecision)

    def _forward_impl(
        self,
        user_query: str,
        candidates: List[Dict[str, str]],
        forced_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 1) Category
        if forced_category in {"water", "electricity"}:
            category = forced_category
        else:
            cat = self.classify(user_query=user_query).category.strip().lower()
            if "water" in cat:
                category = "water"
            elif "electric" in cat:
                category = "electricity"
            else:
                category = None

        if category is None:
            return {"need_category": True, "buttons": _category_buttons(), "category": None, "top5": []}

        # 2) Rank
        cj = json.dumps(
            [{"code": it["code"], "desc": it["desc"], "full_desc": it.get("_full_desc", "")} for it in candidates],
            ensure_ascii=False,
        )
        out = self.rank(user_query=user_query, candidates_json=cj).top5
        top5 = _parse_top5(out)

        # Relevance guard
        tokens = [t for t in user_query.lower().split() if len(t) > 2]

        def _has_overlap(it: Dict[str, str]) -> bool:
            hay = (it.get("desc", "")).lower()
            return any(t in hay for t in tokens)

        if not top5 or sum(1 for it in top5 if _has_overlap(it)) == 0:
            return {"need_category": True, "buttons": _category_buttons(), "category": None, "top5": []}

        return {"need_category": False, "buttons": [], "category": category, "top5": top5[:5]}

    def forward(
        self,
        user_query: str,
        candidates: List[Dict[str, str]],
        forced_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Wrapped forward method with circuit breaker protection.
        """
        from src.core.circuit_breaker import CircuitBreakerOpen
        try:
            return self._forward_impl(user_query, candidates, forced_category)
        except CircuitBreakerOpen:
            # Graceful fallback when circuit is open
            logger.warning("Circuit breaker open - returning safe fallback")
            return {"need_category": True, "buttons": _category_buttons(), "category": None, "top5": []}


def _category_buttons() -> List[Dict[str, str]]:
    return [{"label": "water", "value": "water"}, {"label": "electricity", "value": "electricity"}]


def _parse_top5(raw: Any) -> List[Dict[str, str]]:
    """
    Robust parsing of the LLM's top5 output into a list of dicts.
    The actual implementation logic remains in app.py; this helper
    is intentionally conservative to avoid behavior drift.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            # Try JSON first
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception:
            try:
                # Fallback to literal eval style lists
                import ast

                data = ast.literal_eval(raw)
                if isinstance(data, list):
                    return data
            except Exception:
                logger.warning("Failed to parse top5 output from DSPy pipeline")
    return []


def get_classification_pipeline() -> CallTypePipeline:
    """
    Returns configured DSPy classification pipeline.

    Caller can hold onto the returned instance, or use the module-level
    singleton via `pipeline`.
    """
    return CallTypePipeline()


def initialize_pipeline() -> None:
    """
    Initialize the DSPy pipeline on application startup.
    
    This function ensures the language model is configured and the pipeline
    is ready for use. It's called during FastAPI startup event.
    Must be called from the async startup context to avoid DSPy async issues.
    """
    global pipeline
    # Configure LM first (must happen in async startup context)
    _configure_lm()
    # Then get the pipeline
    pipeline = get_classification_pipeline()
    logger.info("DSPy classification pipeline initialized")


# Module-level singleton - will be initialized during startup
# Initialize to None, will be set by initialize_pipeline()
pipeline: Optional[CallTypePipeline] = None


# Additional high-level helpers (context analyzer, clarifying questions)
# Wrap with circuit breaker for resilience (Phase 8)
# Base predictors (unwrapped)
_base_context_analyzer = dspy.Predict(UnderstandContext)
_base_clarifying_question_generator = dspy.Predict(GenerateClarifyingQuestion)


@azure_circuit
def _safe_context_analyzer(user_story: str):
    """Wrapped context analyzer with circuit breaker."""
    return _base_context_analyzer(user_story=user_story)


@azure_circuit
def _safe_clarifying_question_generator(user_message: str, service_category: str):
    """Wrapped clarifying question generator with circuit breaker."""
    return _base_clarifying_question_generator(
        user_message=user_message,
        service_category=service_category
    )


# Public API - use wrapped versions
context_analyzer = _safe_context_analyzer
clarifying_question_generator = _safe_clarifying_question_generator


__all__ = [
    "CallTypePipeline",
    "RouteDecision",
    "UnderstandContext",
    "ClassifyCategory",
    "GenerateClarifyingQuestion",
    "RankTop5",
    "get_classification_pipeline",
    "initialize_pipeline",
    "pipeline",
    "context_analyzer",
    "clarifying_question_generator",
]

# Note: issue_normalizer is in its own module (src/core/issue_normalizer.py)
# and does not need to be imported here. It will be used directly by the orchestrator
# when Phase 2 wiring is implemented.

