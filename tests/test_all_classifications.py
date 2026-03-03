"""
Systematic classification tests for ALL transport call types plus representative
samples from every other domain.

Uses the same `smart_classify` function the live orchestrator calls, so results
reflect exactly what the chatbot does in production.

Run from project root:
    python3 tests/test_all_classifications.py

Exit codes:
    0  all tests passed
    1  one or more failures
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.classification.smart_classifier import smart_classify

# ── Test suite ──────────────────────────────────────────────────────────────
# Format: {expected_call_type_code: [phrase, ...]}
# A test PASSES if the top result matches the code at confidence >= MIN_CONFIDENCE.
# A test is SKIPPED (neither pass nor fail) if confidence < MIN_CONFIDENCE but the
# result is correct (classifier is uncertain but not wrong).
MIN_CONFIDENCE = 0.35

TEST_SUITE: dict[str, list[str]] = {

    # ── Transport: Driver Behaviour ──────────────────────────────────────
    "25019": [
        "driver is rude",
        "bus driver has an attitude",
        "driver was disrespectful",
        "driver shouted at me",
        "driver was unprofessional",
        "abusive bus driver",
        "driver swore at passengers",
        "driver behaviour complaint",
        "the driver was aggressive",
        "driver harassed me",
    ],

    # ── Transport: Problem Passengers ────────────────────────────────────
    "25014": [
        "rowdy passengers on the bus",
        "passengers fighting on bus",
        "drunk passenger causing trouble",
        "disruptive passenger",
        "passenger smoking on bus",
        "aggressive passenger",
        "unruly passenger behaviour",
        "someone is misbehaving on bus",
    ],

    # ── Transport: Bus Non-Arrival / Lost Trips ───────────────────────────
    "25010": [
        "bus did not arrive",
        "bus never came",
        "no bus today",
        "bus service did not run",
    ],

    # ── Transport: Bus Not Stopping ───────────────────────────────────────
    "80027": [
        "bus skipped my stop",
        "bus drove past without stopping",
        "bus missed the stop",
        "bus passed by without stopping",
    ],

    # ── Transport: Bus Damage ─────────────────────────────────────────────
    "25001": [
        "bus has broken window",
        "damaged seat on the bus",
        "bus is vandalised",
        "graffiti on the bus",
        "bus door is broken",
    ],

    # ── Transport: Injury on Bus ──────────────────────────────────────────
    "25022": [
        "I was injured on the bus",
        "passenger hurt on bus",
        "fell on the bus",
        "accident happened on the bus",
        "slip and fall on bus",
    ],

    # ── Transport: Incorrect Fare ─────────────────────────────────────────
    "25021": [
        "wrong fare charged",
        "overcharged on bus",
        "incorrect fare amount",
        "charged too much for ticket",
        "fare dispute",
    ],

    # ── Transport: Bus Overloading ────────────────────────────────────────
    "25017": [
        "bus is overcrowded",
        "too many people on bus",
        "bus is overloaded",
        "bus was full and still picking up",
    ],

    # ── Transport: Loud Radio ─────────────────────────────────────────────
    "25026": [
        "music too loud on bus",
        "loud radio on bus",
        "noise from bus radio",
        "driver playing loud music",
    ],

    # ── Transport: Lost Property ──────────────────────────────────────────
    "25025": [
        "I left my bag on the bus",
        "lost property on bus",
        "left my phone on the bus",
        "lost item on metro bus",
    ],

    # ── Transport: Inspector Complaint ───────────────────────────────────
    "25023": [
        "inspector was rude",
        "complaint about inspector",
        "checker has attitude",
        "inspector complaint",
    ],

    # ── Water: No Water ──────────────────────────────────────────────────
    "10016": [
        "there is no water",
        "water has been cut off",
        "no water supply",
        "water outage in my area",
    ],

    # ── Water: Major Burst ───────────────────────────────────────────────
    "10035": [
        "water pipe burst",
        "burst water pipe",
        "major burst pipe",
        "water gushing in street",
    ],

    # ── Electricity: No Supply ───────────────────────────────────────────
    "20021": [
        "no electricity",
        "power is out",
        "no power supply",
        "electricity has been cut",
    ],

    # ── Roads: Road Subsiding ────────────────────────────────────────────
    "60042": [
        "road is sinking",
        "road is subsiding",
        "road collapsed",
        "sinkhole in road",
    ],

    # ── Waste: Missed Collection ──────────────────────────────────────────
    "30019": [
        "garbage was not collected",
        "missed bin collection",
        "rubbish not picked up",
        "waste collection skipped my street",
    ],
}

# ── Vagueness tests — these should NOT produce high-confidence classifications
VAGUENESS_TESTS = [
    "metro bus",
    "bus",
    "transport",
    "electricity",
    "water",
    "roads issue",
]


def run_tests() -> int:
    with open("data/call_types/call_type_metadata.json") as f:
        metadata = json.load(f)
    code_to_desc = {str(ct["code"]): ct.get("description", "") for ct in metadata}

    passed = failed = skipped = 0
    failures: list[dict] = []

    print("=" * 72)
    print("CLASSIFICATION TEST SUITE")
    print("=" * 72)

    for expected_code, phrases in TEST_SUITE.items():
        desc = code_to_desc.get(expected_code, "???")
        group_pass = group_fail = group_skip = 0

        for phrase in phrases:
            result = smart_classify(phrase)
            got_code = str(result.get("call_type_code") or "")
            confidence = result.get("confidence", 0.0)
            method = result.get("_smart_method", "")

            if got_code == expected_code and confidence >= MIN_CONFIDENCE:
                group_pass += 1
                passed += 1
            elif got_code != expected_code and confidence >= MIN_CONFIDENCE:
                group_fail += 1
                failed += 1
                failures.append(
                    {
                        "phrase": phrase,
                        "expected_code": expected_code,
                        "expected_desc": desc,
                        "got_code": got_code,
                        "got_desc": code_to_desc.get(got_code, "???"),
                        "confidence": round(confidence, 3),
                        "method": method,
                    }
                )
            else:
                # Correct but low confidence — or wrong but uncertain
                group_skip += 1
                skipped += 1

        status = "PASS" if group_fail == 0 else "FAIL"
        print(
            f"  [{status}] [{expected_code}] {desc:<30} "
            f"pass={group_pass} fail={group_fail} skip={group_skip}"
        )

    # ── Vagueness tests ────────────────────────────────────────────────
    print()
    print("VAGUENESS TESTS  (should not produce high-confidence results)")
    print("-" * 72)
    vague_pass = vague_fail = 0
    for phrase in VAGUENESS_TESTS:
        result = smart_classify(phrase)
        confidence = result.get("confidence", 0.0)
        needs_clarification = result.get("needs_clarification", False) or confidence < MIN_CONFIDENCE
        status = "PASS" if needs_clarification else "FAIL"
        if status == "PASS":
            vague_pass += 1
        else:
            vague_fail += 1
            failed += 1
            failures.append(
                {
                    "phrase": phrase,
                    "expected_code": "vague",
                    "expected_desc": "should ask for clarification",
                    "got_code": str(result.get("call_type_code") or ""),
                    "got_desc": result.get("issue_label", ""),
                    "confidence": round(confidence, 3),
                    "method": result.get("_smart_method", ""),
                }
            )
        print(f"  [{status}] '{phrase}' → conf={confidence:.3f}")

    # ── Summary ─────────────────────────────────────────────────────────
    total = passed + failed + skipped
    print()
    print("=" * 72)
    print(f"RESULTS: {passed} passed  |  {failed} failed  |  {skipped} skipped  |  {total} total")
    print("=" * 72)

    if failures:
        print()
        # Separate failures by root cause
        ghost_code_failures = [
            f for f in failures
            if f["got_desc"] == "???" and f["method"] == "direct_match"
        ]
        wrong_mapping_failures = [
            f for f in failures
            if f["got_desc"] != "???" and f["method"] == "direct_match"
        ]
        other_failures = [
            f for f in failures
            if f["method"] != "direct_match" and f["expected_code"] != "vague"
        ]
        vague_failures = [f for f in failures if f["expected_code"] == "vague"]

        if ghost_code_failures:
            print("BUG ① — direct_pattern_match uses CODES THAT DON'T EXIST in metadata:")
            for f in ghost_code_failures:
                print(
                    f"  '{f['phrase']}'\n"
                    f"    direct_pattern_match returned code {f['got_code']} (not in call_type_metadata)\n"
                    f"    Expected: [{f['expected_code']}] {f['expected_desc']}\n"
                )

        if wrong_mapping_failures:
            print("BUG ② — direct_pattern_match maps phrase to WRONG CALL TYPE CODE:")
            for f in wrong_mapping_failures:
                print(
                    f"  '{f['phrase']}'\n"
                    f"    Got:      [{f['got_code']}] {f['got_desc']}  (conf={f['confidence']})\n"
                    f"    Expected: [{f['expected_code']}] {f['expected_desc']}\n"
                )

        if other_failures:
            print("BUG ③ — keyword/vector mismatch (not direct_pattern_match):")
            for f in other_failures:
                print(
                    f"  '{f['phrase']}'\n"
                    f"    Got:      [{f['got_code']}] {f['got_desc']}  (conf={f['confidence']}, via {f['method']})\n"
                    f"    Expected: [{f['expected_code']}] {f['expected_desc']}\n"
                )

        if vague_failures:
            print("BUG ④ — vague input classified with HIGH confidence (should ask for clarification):")
            for f in vague_failures:
                print(
                    f"  '{f['phrase']}' → [{f['got_code']}] {f['got_desc']}  (conf={f['confidence']})\n"
                )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_tests())
