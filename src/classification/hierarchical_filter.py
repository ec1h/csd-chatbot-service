"""
Extract domain hierarchy from call type data.

Reads all call type JSON files and builds a structured domain →
category → call_type hierarchy used by the retrieval layer.

Field mapping (actual JSON field names):
  intent_bucket  → domain
  issue_category → category
  call_type_code → code
  short_description → description
"""

import json
import os
from typing import Dict, List, Any
from collections import defaultdict


class HierarchyBuilder:
    def __init__(self, data_path: str):
        self.data_path = data_path
        self.call_types: List[Dict[str, Any]] = []

    def load_all_call_types(self) -> List[Dict[str, Any]]:
        """Load and parse all call type JSON files."""
        all_call_types: List[Dict[str, Any]] = []

        for root, _dirs, files in os.walk(self.data_path):
            for file in files:
                if file.endswith(".json") and "call_type" in file.lower():
                    filepath = os.path.join(root, file)
                    with open(filepath, "r") as f:
                        try:
                            data = json.load(f)
                            if isinstance(data, list):
                                all_call_types.extend(data)
                            elif isinstance(data, dict):
                                all_call_types.append(data)
                        except Exception:
                            print(f"Error parsing {filepath}")

        self.call_types = all_call_types
        return all_call_types

    def build_hierarchy(self) -> Dict[str, Any]:
        """Extract domain and category from call types.

        Uses actual field names from the JSON schema:
          intent_bucket  → domain grouping
          issue_category → sub-category within the domain
        """
        hierarchy: Dict[str, Any] = {
            "domains": {},
            "domain_to_categories": defaultdict(list),
            "category_to_call_types": defaultdict(list),
        }

        for ct in self.call_types:
            # Actual field: intent_bucket (e.g. "water", "electricity")
            domain = (
                ct.get("intent_bucket", ct.get("domain", "other")) or "other"
            ).lower()

            # Actual field: issue_category (e.g. "maintenance", "billing")
            category = (
                ct.get("issue_category", ct.get("category", "general")) or "general"
            ).lower()

            # Actual field: call_type_code (e.g. "10078")
            code = str(
                ct.get("call_type_code", ct.get("code", ct.get("Code", "")))
            )

            # Actual field: short_description
            description = ct.get(
                "short_description",
                ct.get("description", ct.get("Description", "")),
            )

            keywords = ct.get("keywords", [])

            if domain not in hierarchy["domains"]:
                hierarchy["domains"][domain] = {"name": domain, "categories": set()}

            hierarchy["domains"][domain]["categories"].add(category)

            if category not in hierarchy["domain_to_categories"][domain]:
                hierarchy["domain_to_categories"][domain].append(category)

            hierarchy["category_to_call_types"][category].append(
                {
                    "code": code,
                    "description": description,
                    "keywords": keywords,
                    "domain": domain,
                }
            )

        # Convert sets to lists for JSON serialisation
        for domain in hierarchy["domains"]:
            hierarchy["domains"][domain]["categories"] = list(
                hierarchy["domains"][domain]["categories"]
            )

        # Convert defaultdicts to plain dicts
        hierarchy["domain_to_categories"] = dict(hierarchy["domain_to_categories"])
        hierarchy["category_to_call_types"] = dict(hierarchy["category_to_call_types"])

        return hierarchy

    def save_hierarchy(self, output_path: str) -> Dict[str, Any]:
        """Build and write hierarchy JSON, returning the result."""
        hierarchy = self.build_hierarchy()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(hierarchy, f, indent=2)
        return hierarchy
