"""
Lightweight analytics helpers for classification performance.

Currently used to:
- Log low-confidence classification events (< 0.3) so that we can
  analyse real user messages that the classifier struggles with.

Log format:
- JSON Lines file at `reports/classification_low_confidence.jsonl`
- Each line is a JSON object with:
    {
      "timestamp": "...",
      "user_text": "...",
      "conversation_state": "...",
      "conversation_history": [...],
      "classification": {...}
    }

This file is **server-side only** and never exposed to users.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable


logger = logging.getLogger(__name__)

# Resolve repo root as: src/utils/ -> src/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
LOW_CONF_FILE = REPORTS_DIR / "classification_low_confidence.jsonl"


def log_low_confidence_classification_event(
    *,
    user_text: str,
    classification: Dict[str, Any],
    conversation_history: Iterable[str],
    conversation_state: str,
) -> None:
    """
    Append a single low-confidence classification event to the JSONL log file.

    This function is deliberately best-effort:
    - It never raises in normal operation (errors are logged at DEBUG level).
    - It tolerates missing directories / file creation races.
    """
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        event: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_text": user_text,
            "conversation_state": conversation_state,
            "conversation_history": list(conversation_history),
            "classification": classification,
        }

        with LOW_CONF_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        # Best-effort only – do not interfere with main flow
        logger.debug("Failed to log low-confidence classification event: %s", e)


__all__ = ["log_low_confidence_classification_event"]

