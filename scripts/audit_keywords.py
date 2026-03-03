"""
Audit all call types for keyword coverage and conflicts.
Run from project root: python3 scripts/audit_keywords.py
"""

import json
import os
from collections import Counter, defaultdict

DATA_PATH = "data/call_types/call_type_metadata.json"
OUTPUT_PATH = "data/call_types/keyword_conflicts.json"


def audit_keywords():
    with open(DATA_PATH, "r") as f:
        call_types = json.load(f)

    print(f"Auditing {len(call_types)} call types\n")

    stats = {
        "total_call_types": len(call_types),
        "with_keywords": 0,
        "total_keyword_count": 0,
        "domains": Counter(),
    }

    keyword_to_codes: dict[str, list] = defaultdict(list)
    all_keywords: list[str] = []

    for ct in call_types:
        code = ct.get("code")
        domain = ct.get("domain", "unknown")
        keywords = ct.get("keywords", [])

        stats["domains"][domain] += 1

        if keywords:
            stats["with_keywords"] += 1
            stats["total_keyword_count"] += len(keywords)
            all_keywords.extend(keywords)
            for kw in keywords:
                keyword_to_codes[kw].append(code)

    avg_kw = stats["total_keyword_count"] / max(1, stats["with_keywords"])

    conflicts = {kw: codes for kw, codes in keyword_to_codes.items() if len(codes) > 1}

    print("=== KEYWORD AUDIT RESULTS ===")
    print(f"Total call types       : {stats['total_call_types']}")
    print(f"With keywords          : {stats['with_keywords']} ({stats['with_keywords']/stats['total_call_types']*100:.1f}%)")
    print(f"Avg keywords per type  : {avg_kw:.1f}")
    print(f"Total unique keywords  : {len(set(all_keywords))}")
    print(f"Conflicting keywords   : {len(conflicts)}")

    print("\n=== DOMAIN BREAKDOWN ===")
    for domain, count in stats["domains"].most_common():
        print(f"  {domain:<20} {count} call types")

    print("\n=== TOP 15 CONFLICTS ===")
    top_conflicts = sorted(conflicts.items(), key=lambda x: len(x[1]), reverse=True)[:15]
    for kw, codes in top_conflicts:
        print(f"  {kw!r:<35} shared by {len(codes)} types: {', '.join(str(c) for c in codes[:4])}")

    print("\n=== CALL TYPES WITH ZERO KEYWORDS ===")
    zero_kw = [ct for ct in call_types if not ct.get("keywords")]
    for ct in zero_kw:
        print(f"  [{ct.get('code')}] {ct.get('description', 'N/A')}")
    if not zero_kw:
        print("  None — all call types have keywords.")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(conflicts, f, indent=2)
    print(f"\nConflicts written to {OUTPUT_PATH}")

    return conflicts


if __name__ == "__main__":
    audit_keywords()
