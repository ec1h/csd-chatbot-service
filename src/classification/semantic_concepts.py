"""
Semantic Concept Layer for CSD Chatbot
--------------------------------------
A preprocessing layer that detects semantic concepts from user input
and applies department gating + call type boosting.

Concepts are:
- Reusable meaning buckets (not tied to specific keywords)
- Department-safe (gate which departments are allowed)
- Deterministic (no LLM, pattern-based detection)
- Scoring-based (boost or penalize call types)

This module sits between user input and call type matching.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Concept:
    """
    A semantic concept represents a reusable meaning bucket.

    Attributes:
        name: Unique identifier for the concept
        patterns: List of regex patterns that detect this concept
        allowed_departments: Set of intent_buckets this concept can route to (empty = all allowed)
        blocked_departments: Set of intent_buckets this concept CANNOT route to
        call_type_boosts: Dict mapping call_type patterns to confidence boost values
        call_type_penalties: Dict mapping call_type patterns to confidence penalty values
        priority: Higher priority concepts are evaluated first (default 0)
        is_scene_override: If True, this concept describes a physical scene and takes
                          dominance over dialog flow - it overrides other concepts
    """
    name: str
    patterns: List[str]
    allowed_departments: Set[str] = field(default_factory=set)
    blocked_departments: Set[str] = field(default_factory=set)
    call_type_boosts: Dict[str, float] = field(default_factory=dict)
    call_type_penalties: Dict[str, float] = field(default_factory=dict)
    priority: int = 0
    is_scene_override: bool = False

    def __post_init__(self):
        # Compile patterns for efficiency
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.patterns
        ]

    def matches(self, text: str) -> bool:
        """Check if any pattern matches the text."""
        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return True
        return False

    def get_match_strength(self, text: str) -> float:
        """
        Return match strength (0.0-1.0) based on how many patterns match.
        More matches = stronger concept detection.
        """
        matches = sum(1 for p in self._compiled_patterns if p.search(text))
        if matches == 0:
            return 0.0
        return min(1.0, matches / len(self._compiled_patterns) + 0.5)


@dataclass
class ConceptMatch:
    """Result of concept detection for a single concept."""
    concept: Concept
    strength: float  # 0.0-1.0
    matched_patterns: List[str]


@dataclass
class ConceptDetectionResult:
    """Full result of concept detection on user input."""
    detected_concepts: List[ConceptMatch]
    allowed_departments: Set[str]  # Union of all allowed (empty = all)
    blocked_departments: Set[str]  # Union of all blocked
    call_type_boosts: Dict[str, float]  # Aggregated boosts
    call_type_penalties: Dict[str, float]  # Aggregated penalties
    has_scene_override: bool = False  # True if a scene-dominant concept was detected

    def get_department_filter(self) -> Optional[Set[str]]:
        """
        Return the effective department filter.
        Returns None if no filtering should be applied.
        """
        if not self.allowed_departments and not self.blocked_departments:
            return None

        if self.allowed_departments:
            # Return allowed minus blocked
            return self.allowed_departments - self.blocked_departments

        return None  # Only blocking, no positive filter

    def is_department_allowed(self, department: str) -> bool:
        """Check if a department is allowed given the detected concepts."""
        dept_lower = department.lower()

        # If explicitly blocked, not allowed
        if dept_lower in self.blocked_departments:
            return False

        # If we have allowed list and this isn't in it, not allowed
        if self.allowed_departments and dept_lower not in self.allowed_departments:
            return False

        return True

    def get_boost_for_call_type(self, call_type_desc: str) -> float:
        """Get aggregated boost for a call type description."""
        call_type_lower = call_type_desc.lower()
        total_boost = 0.0

        for pattern, boost in self.call_type_boosts.items():
            if pattern.lower() in call_type_lower:
                total_boost += boost

        return total_boost

    def get_penalty_for_call_type(self, call_type_desc: str) -> float:
        """Get aggregated penalty for a call type description."""
        call_type_lower = call_type_desc.lower()
        total_penalty = 0.0

        for pattern, penalty in self.call_type_penalties.items():
            if pattern.lower() in call_type_lower:
                total_penalty += penalty

        return total_penalty


class ConceptEngine:
    """
    Main engine for detecting and applying semantic concepts.
    """

    def __init__(self):
        self.concepts: List[Concept] = []
        self._load_default_concepts()

    def _load_default_concepts(self):
        """Load the default set of semantic concepts."""

        # =====================================================================
        # SCENE OVERRIDE CONCEPTS - High priority, describe physical scenes
        # These take dominance over dialog flow when user describes what they SEE
        # =====================================================================

        self.concepts.append(Concept(
            name="public_water_flow",
            patterns=[
                r"\bwater\s*(is\s+)?(running|flowing|gushing|pouring|streaming)\s*(down|on|in|across)?\s*(the\s+)?(road|street|pavement)",
                r"\b(road|street|pavement)\s*(is\s+)?(has|with)?\s*(flooded|flooding)\b",
                r"\b(road|street|pavement)\s*(has|with)?\s*water\s*(running|flowing|gushing)",
                r"\bwater\s*(all\s+)?(over|across)\s+(the\s+)?(road|street)",
                r"\b(flooding|flooded)\s*(the\s+)?(road|street|area)",
                r"\bwater\s+coming\s+(out|from)\s*(of\s+)?(the\s+)?(ground|road|street|pavement)",
                r"\bwater\s+everywhere\s*(on|in)\s*(the\s+)?(street|road)",
                r"\b(flooded|flooding)\s*(with\s+)?water\b",
            ],
            allowed_departments={"water"},
            blocked_departments={"electricity", "roads"},
            call_type_boosts={
                "burst": 0.4,
                "leak": 0.35,
                "underground": 0.3,
                "pipe": 0.25,
            },
            call_type_penalties={
                "meter": 0.3,
                "trench": 0.25,
                "excavation": 0.25,
            },
            priority=100,  # Highest priority - scene dominance
            is_scene_override=True
        ))

        # =====================================================================
        # EXCAVATION / CONSTRUCTION WORK CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="road_excavation",
            patterns=[
                r"\b(trench|trenches|trenching)\b",
                r"\b(excavat(e|ed|ion|ions|ing))\b",
                r"\b(dig|dug|digging)\s+(up|in|on|across)?\s*(the\s+)?(road|street|pavement)\b",
                r"\b(hole|holes)\s+(in|on|across)\s+(the\s+)?(road|street)\b",
                r"\bopen\s+(trench|hole|excavation)\b",
                r"\breinstat(e|ed|ement|ing)\b",
                r"\b(road\s+)?work(s)?\s+(in\s+progress|site|area)\b",
            ],
            allowed_departments={"roads"},
            blocked_departments={"water", "electricity"},
            call_type_boosts={
                "trench": 0.3,
                "excavation": 0.3,
                "reinstatement": 0.25,
                "repair road": 0.2,
            },
            call_type_penalties={
                "leak": 0.2,
                "burst": 0.2,
                "meter": 0.15,
            },
            priority=10
        ))

        # =====================================================================
        # WATER INFRASTRUCTURE CONCEPTS (vs private plumbing)
        # =====================================================================

        self.concepts.append(Concept(
            name="public_water_infrastructure",
            patterns=[
                r"\b(in|on|across)\s+(the\s+)?(street|road|pavement|sidewalk)\b.*\b(water|leak|burst|gush)\b",
                r"\b(water|leak|burst|gush).*\b(in|on|across)\s+(the\s+)?(street|road|pavement)\b",
                r"\b(main|mains)\s+(pipe|line|water)\b",
                r"\bwater\s+main\b",
                r"\bpublic\s+(water|pipe|hydrant)\b",
                r"\bfire\s+hydrant\b",
                r"\b(municipal|city)\s+(water|pipe)\b",
                r"\bunderground\s+(leak|pipe|water)\b",
            ],
            allowed_departments={"water"},
            blocked_departments={"electricity", "roads"},
            call_type_boosts={
                "burst": 0.2,
                "underground": 0.25,
                "main": 0.2,
                "hydrant": 0.3,
            },
            call_type_penalties={
                "meter": 0.15,
                "geyser": 0.3,
                "internal": 0.25,
            },
            priority=8
        ))

        self.concepts.append(Concept(
            name="private_plumbing",
            patterns=[
                r"\b(my|inside|in\s+my)\s+(house|home|property|yard|garden)\b.*\b(leak|pipe|tap|water)\b",
                r"\b(leak|pipe|tap|water).*\b(inside|in)\s+(my\s+)?(house|home|property)\b",
                r"\bgeyser\b",
                r"\b(hot\s+water|bathroom|kitchen|toilet)\s+(leak|pipe|tap)\b",
                r"\binternal\s+(leak|pipe|plumbing)\b",
                r"\bprivate\s+plumb(er|ing)\b",
            ],
            blocked_departments={"water", "electricity", "roads"},
            call_type_penalties={
                "burst pipe": 0.4,
                "water main": 0.5,
                "underground": 0.4,
            },
            priority=9
        ))

        # =====================================================================
        # SEWAGE / DRAINAGE CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="sewage_overflow",
            patterns=[
                r"\b(sew(er|age)|drain(age)?)\s*(is\s+)?(overflow|block|clog|smell|stink|backup)",
                r"\b(overflow|block|clog|smell|stink|backup).*\b(sew(er|age)|drain)\b",
                r"\bmanhole\s*(overflow|open|cover|smell)\b",
                r"\b(raw\s+)?sewage\s*(in|on)\s+(the\s+)?(street|road|yard)\b",
                r"\btoilet\s+not\s+flush\b",
                r"\bdrain\s*(is\s+)?(block|clog|slow|back|overflow)",
                r"\bsewage\b(?!.*\b(billing|account|payment)\b)",
                r"\bsewer\s*(line|pipe|system)?\s*(is\s+)?(block|overflow|back|leak)",
            ],
            allowed_departments={"water"},
            blocked_departments={"electricity", "roads", "waste"},
            call_type_boosts={
                "sewer": 0.3,
                "sewage": 0.3,
                "blockage": 0.25,
                "manhole": 0.25,
                "drain": 0.2,
            },
            priority=8
        ))

        # =====================================================================
        # ELECTRICITY CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="street_lighting",
            patterns=[
                r"\bstreet\s*(light|lamp|lighting)\b",
                r"\b(public|pavement|road)\s*light\b",
                r"\blight\s*pole\b",
                r"\b(lamp|light)\s*post\b",
                r"\boutside\s*light.*\b(street|public|pole)\b",
            ],
            allowed_departments={"electricity"},
            blocked_departments={"water", "roads", "waste"},
            call_type_boosts={
                "street light": 0.4,
                "public light": 0.3,
                "lamp": 0.2,
            },
            call_type_penalties={
                "no power": 0.3,
                "outage": 0.25,
                "prepaid": 0.4,
                "meter": 0.3,
            },
            priority=10
        ))

        self.concepts.append(Concept(
            name="power_outage",
            patterns=[
                r"\bno\s*(power|electricity|lights?)\b",
                r"\b(power|electricity)\s*(is\s+)?(out|off|gone|cut)\b",
                r"\bblackout\b",
                r"\b(whole|entire)\s+(area|street|block|neighbourhood|neighborhood)\s*(is\s+)?(dark|without)\b",
                r"\bload\s*shed(ding)?\b",
                r"\b(house|home|property)\s*(has\s+)?(no\s+)?(power|electricity)\b",
                r"\bno\s+(power|electricity)\s*(in|at)?\s*(my\s+)?(house|home|property)\b",
                r"\b(my\s+)?(house|home|property)\s*(has\s+)?no\s+(power|electricity)\b",
                r"\bneighbo[u]?rs?\s+(have|has)\s+(power|electricity)\b",
                r"\bafter\s+(the\s+)?load\s*shed(ding)?\b",
                r"\bsince\s+(the\s+)?load\s*shed(ding)?\b",
            ],
            allowed_departments={"electricity"},
            blocked_departments={"water", "roads"},
            call_type_boosts={
                "outage": 0.3,
                "no power": 0.3,
                "supply": 0.4,
                "no supply": 0.4,
            },
            call_type_penalties={
                "street light": 0.25,
                "prepaid": 0.2,
            },
            priority=10,  # Higher priority to catch home power issues
            is_scene_override=True  # This is a scene description
        ))

        self.concepts.append(Concept(
            name="prepaid_meter",
            patterns=[
                r"\b(prepaid|pre-paid)\s*(meter|electricity)\b",
                r"\b(token|voucher|code)\s*(not\s+)?(load|work|accept|reject)\b",
                r"\bunit(s)?\s*(not\s+)?(load|show|add|credit)\b",
                r"\b(bought|purchased)\s*(units?|electricity|token)\b",
                r"\bmeter\s*(error|code|display|screen|reading)\b",
                r"\brecharge\b.*\b(electricity|meter)\b",
            ],
            allowed_departments={"electricity"},
            blocked_departments={"water", "roads", "billing"},
            call_type_boosts={
                "prepaid": 0.35,
                "token": 0.3,
                "meter": 0.2,
                "vend": 0.25,
            },
            call_type_penalties={
                "street light": 0.4,
                "outage": 0.2,
                "cable": 0.3,
            },
            priority=9
        ))

        # =====================================================================
        # EMERGENCY CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="gas_emergency",
            patterns=[
                r"\bgas\s*(leak|smell|odor|odour)\b",
                r"\bsmell\s*(of\s+)?gas\b",
                r"\b(strong|heavy)\s+gas\s*(smell|odor|odour)?\b",
                r"\bgas\s+(is\s+)?leaking\b",
            ],
            allowed_departments={"emergency"},
            blocked_departments={"water", "electricity", "roads", "waste"},
            call_type_boosts={
                "gas": 0.4,
                "hazard": 0.3,
                "emergency": 0.25,
            },
            priority=15  # High priority - safety critical
        ))

        self.concepts.append(Concept(
            name="active_fire",
            patterns=[
                r"\b(fire|burning|flames?)\s*(right\s+)?now\b",
                # Exclude "fire hydrant" from fire detection
                r"(?<!hydrant\s)(?<!hydrant)\bfire\b(?!\s*hydrant)",
                r"\bsmoke\s*(coming|from|visible)\b",
                r"\b(building|house|car|vehicle|grass|veld|bush)\s*(is\s+)?(on\s+)?fire\b",
                r"\bwildfire\b",
                r"\bfire\s*brigade\b",
            ],
            allowed_departments={"emergency"},
            blocked_departments={"water", "electricity", "roads", "waste", "billing"},
            call_type_boosts={
                "fire": 0.4,
                "burning": 0.3,
                "smoke": 0.25,
            },
            priority=15
        ))

        # =====================================================================
        # WASTE / REFUSE CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="refuse_collection",
            patterns=[
                r"\b(refuse|garbage|trash|rubbish|bin)\s*(not\s+)?(collect|pick|empty|miss)\b",
                r"\b(not\s+)?(collect|pick|empty).*\b(bin|refuse|garbage)\b",
                r"\bmissed\s*(collection|bin|refuse)\b",
                r"\b(bin|refuse)\s+collect\b",
            ],
            allowed_departments={"waste"},
            blocked_departments={"water", "electricity", "roads"},
            call_type_boosts={
                "collection": 0.3,
                "refuse": 0.25,
                "bin": 0.2,
            },
            priority=6
        ))

        self.concepts.append(Concept(
            name="illegal_dumping",
            patterns=[
                r"\billegal\s*(dump|dumping|disposal)\b",
                r"\b(dump|dumping)\s*(site|spot|area|rubbish|rubble)\b",
                r"\bfly\s*tip(ping)?\b",
                r"\brubble\s*(dump|pile|heap)\b",
                r"\b(someone|people)\s+(is\s+|are\s+)?dump\b",
            ],
            allowed_departments={"waste"},
            blocked_departments={"water", "electricity"},
            call_type_boosts={
                "illegal dumping": 0.4,
                "dumping": 0.3,
                "rubble": 0.25,
            },
            priority=6
        ))

        self.concepts.append(Concept(
            name="dead_animal",
            patterns=[
                r"\bdead\s*(animal|dog|cat|bird|rat|rodent)\b",
                r"\b(animal|dog|cat)\s+(is\s+)?dead\b",
                r"\bcarcass\b",
                r"\broadkill\b",
                r"\b(rotting|decomposing)\s*(animal|body|carcass)\b",
            ],
            allowed_departments={"waste"},
            blocked_departments={"water", "electricity", "roads"},
            call_type_boosts={
                "dead animal": 0.4,
                "carcass": 0.35,
                "removal": 0.2,
            },
            priority=7
        ))

        # =====================================================================
        # BILLING CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="billing_query",
            patterns=[
                r"\bmy\s+(bill|account|statement|rates)\b",
                r"\b(bill|account|statement)\s*(query|question|issue|problem|wrong|incorrect)\b",
                r"\b(query|question)\s*(about|regarding)\s*(my\s+)?(bill|account)\b",
                r"\b(too\s+)?(high|incorrect|wrong)\s+(bill|charge|amount)\b",
                r"\bconsumption\s*(query|question|enquiry)\b",
                r"\b(water|electricity)\s+consumption\b(?!.*\b(leak|burst|outage)\b)",
            ],
            allowed_departments={"billing"},
            blocked_departments={"water", "electricity", "roads", "waste"},
            call_type_boosts={
                "billing": 0.3,
                "account": 0.25,
                "query": 0.2,
                "consumption": 0.2,
            },
            call_type_penalties={
                "leak": 0.3,
                "burst": 0.3,
                "outage": 0.3,
                "prepaid": 0.2,
            },
            priority=5
        ))

        # =====================================================================
        # ROADS / TRAFFIC CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="pothole",
            patterns=[
                r"\bpothole\b",
                r"\bhole\s*(in|on)\s+(the\s+)?(road|street|tar)\b",
                r"\broad\s*(damage|crack|broken|surface)\b",
                r"\btar\s*(damage|broken|lifting|crack)\b",
            ],
            allowed_departments={"roads"},
            blocked_departments={"water", "electricity"},
            call_type_boosts={
                "pothole": 0.4,
                "road surface": 0.3,
                "road damage": 0.25,
            },
            priority=6
        ))

        self.concepts.append(Concept(
            name="traffic_signal",
            patterns=[
                r"\btraffic\s*(light|signal|robot)\b",
                r"\brobot\s*(is\s+)?(not\s+)?(work|broken|stuck|flash|off|out)",
                r"\b(red|green|amber|orange)\s+light\s*(stuck|not\s+chang|broken)\b",
                # "robot" as standalone when in traffic context
                r"\b(the\s+)?robot\b(?=.*(not|broken|stuck|flash|work|off))",
            ],
            allowed_departments={"roads"},
            blocked_departments={"water", "electricity", "waste"},
            call_type_boosts={
                "traffic signal": 0.35,
                "traffic light": 0.35,
                "robot": 0.25,
            },
            call_type_penalties={
                "street light": 0.3,
            },
            priority=7
        ))

        # =====================================================================
        # HEALTH / ENVIRONMENTAL CONCEPTS
        # =====================================================================

        self.concepts.append(Concept(
            name="pest_infestation",
            patterns=[
                r"\b(rat|rats|mouse|mice|cockroach|roach)\s*(infestation|problem|issue)?\b",
                r"\b(infestation|infested)\s*(with|of)?\s*(rat|mice|roach|pest)\b",
                r"\bpest\s*(control|problem|infestation)\b",
                r"\brodent\b",
            ],
            allowed_departments={"health"},
            blocked_departments={"water", "electricity", "roads", "waste"},
            call_type_boosts={
                "pest": 0.35,
                "rodent": 0.3,
                "infestation": 0.25,
            },
            priority=6
        ))

        self.concepts.append(Concept(
            name="noise_complaint",
            patterns=[
                r"\bnoise\s*(complaint|problem|issue|nuisance)\b",
                r"\b(loud|excessive)\s*(music|noise|party|sound)\b",
                r"\b(neighbour|neighbor)\s*(is\s+)?(noisy|loud|playing)\b",
                r"\bdisturbance\b",
            ],
            allowed_departments={"health"},
            blocked_departments={"water", "electricity", "roads"},
            call_type_boosts={
                "noise": 0.35,
                "nuisance": 0.25,
                "disturbance": 0.25,
            },
            priority=5
        ))

    def register_concept(self, concept: Concept):
        """Register a new concept with the engine."""
        self.concepts.append(concept)
        # Re-sort by priority
        self.concepts.sort(key=lambda c: c.priority, reverse=True)

    def detect(self, text: str) -> ConceptDetectionResult:
        """
        Detect all matching concepts in the given text.

        Returns a ConceptDetectionResult with:
        - All detected concepts and their match strengths
        - Aggregated department allowances/blocks
        - Aggregated call type boosts/penalties
        - has_scene_override flag if a scene-dominant concept was detected
        """
        detected = []
        allowed_depts: Set[str] = set()
        blocked_depts: Set[str] = set()
        boosts: Dict[str, float] = {}
        penalties: Dict[str, float] = {}
        has_scene_override = False
        scene_override_concept: Optional[Concept] = None

        for concept in self.concepts:
            if concept.matches(text):
                strength = concept.get_match_strength(text)

                # Track matched patterns for debugging
                matched_patterns = [
                    p for p, compiled in zip(concept.patterns, concept._compiled_patterns)
                    if compiled.search(text)
                ]

                detected.append(ConceptMatch(
                    concept=concept,
                    strength=strength,
                    matched_patterns=matched_patterns
                ))

                # Check for scene override - highest priority scene concept wins
                if concept.is_scene_override:
                    if not has_scene_override or concept.priority > scene_override_concept.priority:
                        has_scene_override = True
                        scene_override_concept = concept

        # If we have a scene override, it takes dominance
        if has_scene_override and scene_override_concept:
            # Scene override concept's departments take full control
            allowed_depts = scene_override_concept.allowed_departments.copy()
            blocked_depts = scene_override_concept.blocked_departments.copy()

            # Only apply boosts/penalties from the scene override concept
            for pattern, boost in scene_override_concept.call_type_boosts.items():
                boosts[pattern] = boost
            for pattern, penalty in scene_override_concept.call_type_penalties.items():
                penalties[pattern] = penalty
        else:
            # Normal aggregation logic for non-scene concepts
            for match in detected:
                concept = match.concept
                strength = match.strength

                # Aggregate department constraints
                if concept.allowed_departments:
                    if not allowed_depts:
                        allowed_depts = concept.allowed_departments.copy()
                    else:
                        # Intersect allowed departments (must satisfy all)
                        allowed_depts &= concept.allowed_departments

                blocked_depts |= concept.blocked_departments

                # Aggregate boosts (scaled by match strength)
                for pattern, boost in concept.call_type_boosts.items():
                    current = boosts.get(pattern, 0.0)
                    boosts[pattern] = current + (boost * strength)

                # Aggregate penalties (scaled by match strength)
                for pattern, penalty in concept.call_type_penalties.items():
                    current = penalties.get(pattern, 0.0)
                    penalties[pattern] = current + (penalty * strength)

        return ConceptDetectionResult(
            detected_concepts=detected,
            allowed_departments=allowed_depts,
            blocked_departments=blocked_depts,
            call_type_boosts=boosts,
            call_type_penalties=penalties,
            has_scene_override=has_scene_override
        )


# Global singleton instance
_concept_engine: Optional[ConceptEngine] = None


def get_concept_engine() -> ConceptEngine:
    """Get or create the global concept engine instance."""
    global _concept_engine
    if _concept_engine is None:
        _concept_engine = ConceptEngine()
    return _concept_engine


def detect_concepts(text: str) -> ConceptDetectionResult:
    """
    Convenience function to detect concepts in text.
    Uses the global concept engine instance.
    """
    return get_concept_engine().detect(text)


def apply_concept_adjustments(
    matches: List[Dict],
    concept_result: ConceptDetectionResult
) -> List[Dict]:
    """
    Apply concept-based adjustments to call type matches.

    This function:
    1. Filters out matches from blocked departments
    2. Applies confidence boosts from matching concepts
    3. Applies confidence penalties from matching concepts
    4. Re-sorts by adjusted confidence

    Args:
        matches: List of call type match dicts with 'confidence', 'short_description', 'intent_bucket'
        concept_result: Result from concept detection

    Returns:
        Adjusted and filtered list of matches
    """
    adjusted = []

    for match in matches:
        intent_bucket = match.get("intent_bucket", "").lower()

        # Check department allowance
        if not concept_result.is_department_allowed(intent_bucket):
            continue

        # Get call type description for boost/penalty lookup
        desc = match.get("short_description", "")

        # Calculate adjustments
        boost = concept_result.get_boost_for_call_type(desc)
        penalty = concept_result.get_penalty_for_call_type(desc)

        # Apply adjustments
        original_conf = match.get("confidence", 0.0)
        adjusted_conf = original_conf + boost - penalty
        adjusted_conf = min(1.0, max(0.0, adjusted_conf))

        # Create adjusted match
        adjusted_match = match.copy()
        adjusted_match["confidence"] = round(adjusted_conf, 3)
        adjusted_match["_original_confidence"] = original_conf
        adjusted_match["_concept_boost"] = round(boost, 3)
        adjusted_match["_concept_penalty"] = round(penalty, 3)

        adjusted.append(adjusted_match)

    # Re-sort by adjusted confidence
    adjusted.sort(key=lambda x: x["confidence"], reverse=True)

    return adjusted
