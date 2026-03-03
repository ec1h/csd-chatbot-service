"""
Domain Detector (classification layer)
=======================================
Fast, multi-domain detection using keyword scoring and regex patterns.

Returns a ranked list of domain names (using intent_bucket values from
the call type data: water, electricity, roads, waste, transport, …).

This is distinct from src/conversation/domain_detector.py which handles
the OPEN-state "domain-only input" rule (single-word inputs like "water").
This module scores the full message and returns a confidence-ranked list.
"""

import json
import re
from typing import Dict, List, Optional


class DomainDetector:
    """Score a user message against known domains and return ranked results."""

    def __init__(self, hierarchy_path: str):
        with open(hierarchy_path, "r") as f:
            self.hierarchy = json.load(f)

        self.domain_keywords = self._build_domain_keywords()
        self.domain_patterns = self._build_domain_patterns()

    # ------------------------------------------------------------------
    # Build-time helpers
    # ------------------------------------------------------------------

    def _build_domain_keywords(self) -> Dict[str, List[str]]:
        """Build keyword index per domain from the hierarchy."""
        keywords: Dict[str, List[str]] = {}

        for domain, data in self.hierarchy["domains"].items():
            domain_words: set = set(domain.split())

            for category in data.get("categories", []):
                domain_words.update(category.split())

            # Simple plural/singular variations
            variations = list(domain_words)
            for word in list(domain_words):
                if word.endswith("s") and len(word) > 2:
                    variations.append(word[:-1])
                if word.endswith("y") and len(word) > 2:
                    variations.append(word[:-1] + "ie")

            keywords[domain] = list(set(variations))

        return keywords

    def _build_domain_patterns(self) -> Dict[str, List[str]]:
        """Curated regex patterns per known domain."""
        return {
            "water": [
                r"\bwater\b",
                r"\bleak\b",
                r"\bsewer\b",
                r"\bplumbing\b",
                r"\btap\b",
                r"\bfaucet\b",
                r"\bpipe\b",
                r"\bflood",
                r"\bdrain\b",
                r"\bpressure\b",
            ],
            "electricity": [
                r"\belectric",
                r"\bpower\b",
                r"\boutage\b",
                r"\bblackout\b",
                r"\bfuse\b",
                r"\bcircuit\b",
                r"\bstreet\s*light\b",
                r"\btraffic\s*light\b",
                r"\bmeter\b",
            ],
            "roads": [
                r"\broad\b",
                r"\bstreet\b",
                r"\bpothole\b",
                r"\bpavement\b",
                r"\bsidewalk\b",
                r"\bhighway\b",
                r"\btarmac\b",
                r"\bpatch\b",
            ],
            "waste": [
                r"\bwaste\b",
                r"\btrash\b",
                r"\bgarbage\b",
                r"\brubbish\b",
                r"\brecycling\b",
                r"\bbin\b",
                r"\bdump",
                r"\brefuse\b",
                r"\bcollection\b",
            ],
            "transport": [
                r"\bbus\b",
                r"\btaxi\b",
                r"\btrain\b",
                r"\bmetro\b",
                r"\btransport\b",
                r"\btransit\b",
                r"\bstation\b",
                r"\brea\s*vaya\b",
                r"\bmetrobus\b",
            ],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, text: str) -> List[str]:
        """Return a list of domain names sorted by descending confidence score."""
        text_lower = text.lower()
        domain_scores: Dict[str, float] = {}

        # Pattern scoring (weighted higher)
        for domain, patterns in self.domain_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    domain_scores[domain] = domain_scores.get(domain, 0.0) + 1.5

        # Keyword scoring
        for domain, keywords in self.domain_keywords.items():
            for keyword in keywords:
                if keyword and keyword in text_lower:
                    domain_scores[domain] = domain_scores.get(domain, 0.0) + 1.0

        sorted_domains = sorted(
            domain_scores.items(), key=lambda x: x[1], reverse=True
        )
        return [d[0] for d in sorted_domains[:3]]

    def get_primary_domain(self, text: str) -> Optional[str]:
        """Return the single highest-confidence domain, or None."""
        domains = self.detect(text)
        return domains[0] if domains else None
