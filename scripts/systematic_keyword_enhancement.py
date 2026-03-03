"""
Systematic keyword enhancement for all call types.
Applies domain-specific templates and description-derived terms to every call type,
then writes the result to data/call_types/call_type_metadata_enhanced.json.

Run from project root: python3 scripts/systematic_keyword_enhancement.py
"""

import json
import os
import re
from collections import Counter
from typing import Dict, List, Set

METADATA_PATH = "data/call_types/call_type_metadata.json"
TEMPLATES_PATH = "data/keyword_templates.json"
OUTPUT_PATH = "data/call_types/call_type_metadata_enhanced.json"

# Stopwords to strip when deriving terms from descriptions
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for",
    "from", "has", "have", "he", "i", "in", "is", "it", "its", "of",
    "on", "or", "that", "the", "their", "there", "they", "this", "to",
    "was", "were", "will", "with", "my", "me", "we", "our", "not",
    "no", "do", "can", "about", "request", "joburg", "metro",
    "services", "service", "report", "reporting",
}


class SystematicKeywordEnhancer:
    def __init__(self):
        with open(TEMPLATES_PATH, "r") as f:
            self.templates: Dict = json.load(f)
        with open(METADATA_PATH, "r") as f:
            self.call_types: List[Dict] = json.load(f)

    # ------------------------------------------------------------------
    # Domain / issue detection
    # ------------------------------------------------------------------

    def _detect_issue_type(self, ct: Dict, domain: str) -> str:
        """Return the best-matching issue type within the domain."""
        text = (
            ct.get("description", "") + " " + ct.get("issue_type", "")
        ).lower()

        if domain not in self.templates:
            return "general"

        best_issue, best_score = "general", 0
        for issue_type, keywords in self.templates[domain]["issue_types"].items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score, best_issue = score, issue_type

        return best_issue

    # ------------------------------------------------------------------
    # Keyword generation
    # ------------------------------------------------------------------

    def _description_terms(self, ct: Dict) -> Set[str]:
        """Extract meaningful single words from the call type description."""
        raw = " ".join([
            ct.get("description", ""),
            ct.get("issue_type", ""),
            ct.get("category", ""),
        ]).lower()
        words = re.findall(r"\b[a-z]{3,}\b", raw)
        return {w for w in words if w not in _STOPWORDS}

    def generate_keywords(self, ct: Dict) -> List[str]:
        """Build a deduplicated, sorted keyword list for one call type."""
        domain = ct.get("domain", "general")
        issue_type = self._detect_issue_type(ct, domain)

        keywords: Set[str] = set()

        # 1. Keep existing keywords
        keywords.update(ct.get("keywords", []))

        # 2. Add domain base terms
        if domain in self.templates:
            keywords.update(self.templates[domain]["base_terms"])

        # 3. Add issue-type-specific phrases (these are the precise, non-generic ones)
        if domain in self.templates and issue_type in self.templates[domain]["issue_types"]:
            keywords.update(self.templates[domain]["issue_types"][issue_type])

        # 4. Add description-derived single words for extra recall
        keywords.update(self._description_terms(ct))

        # 5. Add example utterances if present
        for utt in ct.get("example_utterances", []):
            if isinstance(utt, str):
                keywords.add(utt.lower().strip())

        # Remove empty strings
        keywords.discard("")
        return sorted(keywords)

    # ------------------------------------------------------------------
    # Conflict reduction
    # ------------------------------------------------------------------

    def _resolve_bus_damage_conflict(self, enhanced: List[Dict]) -> None:
        """
        Targeted fix: narrow BUS DAMAGE keywords so they don't steal
        driver-behaviour or other bus-related queries.
        Codes 25001 and 80001 are BUS DAMAGE call types.
        """
        damage_precise = [
            "bus damage", "damaged bus", "bus vandalized", "broken window on bus",
            "seat damaged on bus", "bus graffiti", "vandalism on bus",
            "bus crashed", "bus accident damage", "smashed bus window",
        ]
        generic_to_remove = {"bus", "metro", "metro bus", "bus bus", "on bus"}

        for ct in enhanced:
            if ct.get("code") in ("25001", "80001") or ct.get("description", "").upper() == "BUS DAMAGE":
                ct["keywords"] = sorted(
                    (set(ct["keywords"]) - generic_to_remove) | set(damage_precise)
                )

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def enhance_all(self) -> List[Dict]:
        enhanced: List[Dict] = []
        domain_stats: Dict[str, Dict] = {}

        for ct in self.call_types:
            new_keywords = self.generate_keywords(ct)
            ct = dict(ct)  # shallow copy – don't mutate original
            ct["keywords"] = new_keywords
            ct["keyword_count"] = len(new_keywords)
            ct["detected_issue_type"] = self._detect_issue_type(ct, ct.get("domain", "general"))
            enhanced.append(ct)

            domain = ct.get("domain", "unknown")
            domain_stats.setdefault(domain, {"count": 0, "total_kw": 0})
            domain_stats[domain]["count"] += 1
            domain_stats[domain]["total_kw"] += len(new_keywords)

        # Targeted conflict resolution
        self._resolve_bus_damage_conflict(enhanced)

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(enhanced, f, indent=2)

        # Summary
        print("=== ENHANCEMENT SUMMARY ===")
        print(f"{'Domain':<20} {'Types':>6}  {'Avg KW':>8}")
        print("-" * 38)
        for domain, s in sorted(domain_stats.items()):
            avg = s["total_kw"] / s["count"]
            print(f"  {domain:<18} {s['count']:>6}  {avg:>8.1f}")

        total_avg = sum(s["total_kw"] for s in domain_stats.values()) / len(enhanced)
        print(f"\n  {'TOTAL':<18} {len(enhanced):>6}  {total_avg:>8.1f} avg keywords")
        print(f"\nOutput written to {OUTPUT_PATH}")

        return enhanced


if __name__ == "__main__":
    enhancer = SystematicKeywordEnhancer()
    enhancer.enhance_all()
