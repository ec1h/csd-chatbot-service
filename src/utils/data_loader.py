"""
Data loading utilities for call types from JSON files
"""
import json
import glob
import logging
from typing import Dict, List, Optional
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent.parent
REFINED_DATA_DIR = SCRIPT_DIR / "data" / "refined data" / "files"

logger = logging.getLogger(__name__)

# Global cache for all call types loaded from JSON
# Exported for use by classification modules
ALL_CALL_TYPES_CACHE: List[Dict] = []
INTENT_BUCKETS: Dict[str, List[Dict]] = {}


def load_all_json_call_types() -> List[Dict]:
    """
    Load all call types from JSON files in the refined data folder.
    Returns a list of all call type objects with their metadata.
    """
    global ALL_CALL_TYPES_CACHE, INTENT_BUCKETS

    if ALL_CALL_TYPES_CACHE:
        return ALL_CALL_TYPES_CACHE

    all_call_types = []

    # First try to load the combined file
    combined_file = REFINED_DATA_DIR / "all_call_types_combined.json"
    if combined_file.exists():
        try:
            with open(combined_file, 'r', encoding='utf-8') as f:
                all_call_types = json.load(f)
                logger.info(f"Loaded {len(all_call_types)} call types from combined JSON file")
        except Exception as e:
            logger.error(f"Failed to load combined JSON file: {e}")

    # If combined file doesn't exist or failed, load individual files
    if not all_call_types:
        json_files = glob.glob(str(REFINED_DATA_DIR / "*.json"))
        for json_file in json_files:
            if "sample_data" in json_file or "combined" in json_file:
                continue  # Skip sample and combined files
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_call_types.extend(data)
                        logger.info(f"Loaded {len(data)} call types from {Path(json_file).name}")
            except Exception as e:
                logger.error(f"Failed to load {json_file}: {e}")

    # Group by intent_bucket
    INTENT_BUCKETS.clear()
    for ct in all_call_types:
        bucket = ct.get("intent_bucket", "unknown").lower()
        if bucket not in INTENT_BUCKETS:
            INTENT_BUCKETS[bucket] = []
        INTENT_BUCKETS[bucket].append(ct)

    ALL_CALL_TYPES_CACHE = all_call_types
    logger.info(f"Total call types loaded: {len(ALL_CALL_TYPES_CACHE)}")
    logger.info(f"Intent buckets: {list(INTENT_BUCKETS.keys())}")

    return ALL_CALL_TYPES_CACHE


def get_call_types_by_intent(intent_bucket: str) -> List[Dict]:
    """Get all call types for a specific intent bucket"""
    if not INTENT_BUCKETS:
        load_all_json_call_types()
    return INTENT_BUCKETS.get(intent_bucket.lower(), [])


def get_all_intent_buckets() -> List[str]:
    """Get list of all available intent buckets"""
    if not INTENT_BUCKETS:
        load_all_json_call_types()
    return list(INTENT_BUCKETS.keys())


def get_fallback_general_call_type() -> Optional[Dict]:
    """
    Return a fallback 'general' call type when we've failed to classify after 3+ misses.
    Used to unblock the user and move to location step.
    """
    if not INTENT_BUCKETS:
        load_all_json_call_types()
    general = INTENT_BUCKETS.get("general", [])
    if not general:
        return None
    ct = general[0]
    code = ct.get("call_type_code")
    if isinstance(code, str):
        try:
            code = int(code)
        except (ValueError, TypeError):
            code = 15001
    return {
        "issue_label": ct.get("short_description") or "General enquiry",
        "call_type_code": code,
        "confidence": 0.5,
    }


__all__ = [
    "load_all_json_call_types",
    "get_call_types_by_intent",
    "get_all_intent_buckets",
    "get_fallback_general_call_type",
    "ALL_CALL_TYPES_CACHE",
    "INTENT_BUCKETS",
]
