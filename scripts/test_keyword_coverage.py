"""
Test keyword coverage against real user phrases — before and after enhancement.
Run from project root: python3 scripts/test_keyword_coverage.py
"""

import json
from collections import defaultdict
from typing import Dict, List, Tuple

ORIGINAL_PATH = "data/call_types/call_type_metadata.json"
ENHANCED_PATH = "data/call_types/call_type_metadata_enhanced.json"

TEST_PHRASES: List[Tuple[str, str]] = [
    # (phrase, expected_description_substring)
    # --- Driver behaviour ---
    ("bus driver was rude to me",            "DRIVER BEHAVIOUR"),
    ("the driver has a bad attitude",         "DRIVER BEHAVIOUR"),
    ("driver shouted at passengers",          "DRIVER BEHAVIOUR"),
    ("bus driver unprofessional",             "DRIVER BEHAVIOUR"),
    ("driver was disrespectful",              "DRIVER BEHAVIOUR"),
    # --- Bus damage ---
    ("bus has a broken window",               "BUS DAMAGE"),
    ("seat is damaged on the bus",            "BUS DAMAGE"),
    ("vandalism on the bus",                  "BUS DAMAGE"),
    # --- Water ---
    ("no water at my house",                  "No Water"),
    ("water leaking from pipe",               "leak"),
    ("dirty brown water coming out",          "quality"),
    ("sewer smell in street",                 "sewer"),
    # --- Electricity ---
    ("power outage in my area",               "Outage"),
    ("street light not working",              "street light"),
    ("lights flickering at home",             "surge"),
    # --- Roads ---
    ("big pothole on main road",              "pothole"),
    ("traffic light broken",                  "traffic light"),
    ("road sign missing",                     "sign"),
    # --- Waste ---
    ("bin not collected this week",           "collection"),
    ("rubbish dumped in vacant lot",          "dump"),
]


def build_index(call_types: List[Dict]) -> Dict[str, List[Dict]]:
    """Map keyword → list of call type dicts."""
    index: Dict[str, List[Dict]] = defaultdict(list)
    for ct in call_types:
        for kw in ct.get("keywords", []):
            index[kw.lower()].append(ct)
    return index


def top_match(phrase: str, index: Dict[str, List[Dict]]) -> Tuple[int, str]:
    """Return (match_count, top_description) for a phrase."""
    phrase_lower = phrase.lower()
    # code → [hit_count, description]
    scored: Dict[str, list] = {}

    for kw, cts in index.items():
        if kw in phrase_lower:
            for ct in cts:
                code = ct["code"]
                if code not in scored:
                    scored[code] = [0, ct.get("description", "")]
                scored[code][0] += 1

    if not scored:
        return 0, "NO MATCH"

    best_code = max(scored, key=lambda c: scored[c][0])
    return scored[best_code][0], scored[best_code][1]


def run_tests(label: str, call_types: List[Dict]) -> int:
    index = build_index(call_types)
    passes = 0
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  {'Phrase':<42} {'Hits':>4}  {'Top Match':<30}  Result")
    print(f"  {'-'*42} {'-'*4}  {'-'*30}  ------")

    for phrase, expected in TEST_PHRASES:
        hits, top_desc = top_match(phrase, index)
        ok = expected.lower() in top_desc.lower()
        status = "PASS" if ok else "FAIL"
        if ok:
            passes += 1
        print(f"  {phrase:<42} {hits:>4}  {top_desc[:30]:<30}  {status}")

    print(f"\n  Result: {passes}/{len(TEST_PHRASES)} passed")
    return passes


def main():
    with open(ORIGINAL_PATH) as f:
        original = json.load(f)
    with open(ENHANCED_PATH) as f:
        enhanced = json.load(f)

    before = run_tests("BEFORE enhancement", original)
    after  = run_tests("AFTER enhancement",  enhanced)

    improvement = after - before
    sign = "+" if improvement >= 0 else ""
    print(f"\n{'='*60}")
    print(f"  IMPROVEMENT: {sign}{improvement} test cases  ({before} → {after})")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
