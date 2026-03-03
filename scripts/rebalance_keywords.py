"""
Systematically rebalance keyword sets across ALL call types.

Approach (same rules applied to every call type — no special cases):
  1. Start from the call type's existing keywords (already enriched by
     systematic_keyword_enhancement.py in a prior run).
  2. Strip generic noise terms that appear in >25 % of all call types
     (they add similarity without discrimination).
  3. Add behavioural synonym expansions from a domain + issue_type table.
  4. Derive meaningful n-grams directly from the description / issue_type.

Nothing is hard-coded per call type.  The same pipeline runs for every row.

Run (from project root):
    python3 scripts/rebalance_keywords.py

Output:
    data/call_types/call_type_metadata_rebalanced.json
    Replaces data/call_types/call_type_metadata.json  (backup made first)
"""

import json
import os
import re
import shutil
import sys
from collections import Counter

# ── Domain + issue_type → discriminative synonyms ──────────────────────────
# Keyed by (domain, normalised_issue_type_word).  Every entry is additive.
# Rules: shorter is better; don't duplicate what's already in keywords.
SYNONYM_TABLE: dict[str, list[str]] = {
    # ── transport / driver ────────────────────────────────────────────────
    "transport:driver":       ["rude driver", "driver rude", "driver attitude",
                               "abusive driver", "aggressive driver",
                               "driver shouted", "driver unprofessional",
                               "bus driver rude", "driver complaint",
                               "driver conduct", "driver harassment"],
    "transport:passenger":    ["rowdy passenger", "rowdy passengers",
                               "disruptive passenger", "aggressive passenger",
                               "fighting on bus", "drunk passenger",
                               "threatening passenger", "harassment on bus",
                               "smoking on bus", "passenger misbehaving",
                               "unruly passenger"],
    "transport:bus":          ["bus not arrived", "late bus", "missed bus",
                               "bus delay", "bus running late"],
    "transport:damage":       ["broken window", "damaged seat", "bus vandalism",
                               "bus graffiti", "bus door broken",
                               "vehicle damage"],
    "transport:lost":         ["lost item", "lost bag", "left belongings",
                               "left item on bus", "property left behind"],
    "transport:fare":         ["wrong fare", "overcharged", "incorrect fare",
                               "charged too much", "fare dispute"],
    "transport:injury":       ["injured on bus", "accident on bus",
                               "hurt on bus", "slip on bus", "fall on bus"],
    "transport:overloading":  ["overcrowded bus", "too many passengers",
                               "bus full", "overloaded bus", "bus packed"],
    "transport:radio":        ["loud music bus", "music too loud",
                               "radio loud", "noise on bus"],
    "transport:inspector":    ["inspector complaint", "inspector rude",
                               "inspector behaviour", "checker attitude"],

    # ── water ─────────────────────────────────────────────────────────────
    "water:leak":             ["water leak", "pipe burst", "leaking pipe",
                               "water running", "burst pipe", "water spillage"],
    "water:meter":            ["meter fault", "meter reading", "meter broken",
                               "water meter issue"],
    "water:no water":         ["no water", "water outage", "water cut",
                               "no supply", "water off"],
    "water:illegal":          ["illegal connection", "water theft",
                               "bypassed meter", "tampering"],

    # ── electricity ───────────────────────────────────────────────────────
    "electricity:outage":     ["power outage", "no electricity", "power cut",
                               "load shedding", "electricity off", "no power"],
    "electricity:meter":      ["prepaid meter", "electricity meter",
                               "meter fault", "meter error"],
    "electricity:illegal":    ["illegal connection", "electricity theft",
                               "power theft", "tampered meter"],
    "electricity:streetlight":["streetlight out", "no street light",
                               "broken streetlight", "dark street"],

    # ── roads ─────────────────────────────────────────────────────────────
    "roads:pothole":          ["pothole", "road pothole", "hole in road",
                               "damaged road", "road damage"],
    "roads:traffic":          ["traffic light", "robot broken", "traffic signal",
                               "broken traffic light"],
    "roads:pavement":         ["broken pavement", "cracked sidewalk",
                               "damaged kerb", "pavement damaged"],

    # ── waste ─────────────────────────────────────────────────────────────
    "waste:missed":           ["missed collection", "garbage not collected",
                               "rubbish not picked up", "skip not emptied",
                               "waste not collected"],
    "waste:illegal":          ["illegal dumping", "fly tipping",
                               "rubbish dumped", "waste dumped illegally"],
    "waste:animal":           ["dead animal", "dead dog", "carcass",
                               "animal carcass removal"],
}

# ── Terms that appear in so many call types they add zero discrimination ───
# Computed dynamically below; these are also always-strip seeds.
ALWAYS_STRIP = {
    "bus", "metro", "metrobus", "minibus", "taxi", "train", "transit",
    "rea vaya", "general", "maintenance", "joburg", "joburg services",
    "service", "services", "request", "services service request",
    "services service", "joburg services service",
    "i have", "my", "there is",        # template noise
}


def normalise(text: str) -> str:
    return text.strip().lower()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def noise_terms(metadata: list[dict], threshold: float = 0.25) -> set[str]:
    """Return keywords that appear in more than `threshold` fraction of entries."""
    total = len(metadata)
    freq: Counter = Counter()
    for ct in metadata:
        for kw in ct.get("keywords", []):
            freq[normalise(kw)] += 1
    return {kw for kw, cnt in freq.items() if cnt / total >= threshold}


def issue_type_keys(domain: str, issue_type: str) -> list[str]:
    """Return synonym-table keys that match this entry's domain + issue_type.

    Matches on prefix/suffix so plurals and variants are caught:
    e.g. 'passengers' matches key 'transport:passenger'
    """
    issue_words = tokens(issue_type)
    matched = []
    for table_key in SYNONYM_TABLE:
        key_domain, key_word = table_key.split(":", 1)
        if key_domain != domain:
            continue
        for word in issue_words:
            if word == key_word or word.startswith(key_word) or key_word.startswith(word):
                matched.append(table_key)
                break
    return list(set(matched))


def description_ngrams(description: str, max_n: int = 3) -> set[str]:
    """Generate unigrams, bigrams, trigrams from the description."""
    words = tokens(description)
    ngrams: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            chunk = " ".join(words[i : i + n])
            if len(chunk) > 2:
                ngrams.add(chunk)
    return ngrams


def rebalance_one(ct: dict, noise: set[str]) -> dict:
    domain = ct.get("domain", "general")
    issue_type = ct.get("issue_type", "")
    description = ct.get("description", "")

    # 1. Start from existing keywords, strip noise
    base: set[str] = {
        normalise(kw)
        for kw in ct.get("keywords", [])
        if normalise(kw) not in noise and normalise(kw) not in ALWAYS_STRIP
    }

    # 2. Add n-grams derived from description
    base |= description_ngrams(description) - noise - ALWAYS_STRIP

    # 3. Add synonym expansions from the domain/issue_type table
    for key in issue_type_keys(domain, issue_type):
        for syn in SYNONYM_TABLE[key]:
            base.add(normalise(syn))

    ct = dict(ct)
    ct["keywords"] = sorted(base)
    ct["keyword_count"] = len(base)
    return ct


def main():
    src = "data/call_types/call_type_metadata.json"
    dst = "data/call_types/call_type_metadata_rebalanced.json"
    bak = "data/call_types/call_type_metadata_pre_rebalance.json"

    with open(src) as f:
        metadata = json.load(f)

    print(f"Loaded {len(metadata)} call types.")

    # Compute noise dynamically
    noise = noise_terms(metadata)
    print(f"Identified {len(noise)} noise terms (appear in ≥25 % of call types).")

    before_total = sum(ct.get("keyword_count", 0) for ct in metadata)

    rebalanced = [rebalance_one(ct, noise) for ct in metadata]

    after_total = sum(ct.get("keyword_count", 0) for ct in rebalanced)
    avg_before = before_total / len(metadata)
    avg_after = after_total / len(rebalanced)

    print(f"\nAverage keywords per call type:")
    print(f"  Before : {avg_before:.1f}")
    print(f"  After  : {avg_after:.1f}")
    print(f"  Change : {avg_after - avg_before:+.1f}")

    # Spot-check the four key call types
    print("\n=== SPOT CHECK ===")
    for ct in rebalanced:
        if ct.get("code") in ("25019", "80019", "25014", "80014"):
            print(f"\n[{ct['code']}] {ct['description']} ({ct['keyword_count']} kw)")
            print(" ", sorted(ct["keywords"])[:20], "…" if len(ct["keywords"]) > 20 else "")

    # Save
    shutil.copy(src, bak)
    print(f"\nBacked up original → {bak}")

    with open(dst, "w") as f:
        json.dump(rebalanced, f, indent=2)
    print(f"Rebalanced metadata written → {dst}")

    # Overwrite live file
    shutil.copy(dst, src)
    print(f"Live file updated → {src}")

    print("\nDone.  Re-run embedding precomputation:")
    print("  python3 scripts/precompute_call_type_embeddings.py --force")


if __name__ == "__main__":
    main()
