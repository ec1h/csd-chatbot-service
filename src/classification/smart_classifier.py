"""
Smart Classifier - Enhanced Classification with Multiple Techniques
====================================================================
This module provides a smarter classification system that:
1. Uses direct pattern matching for common unambiguous issues
2. Falls back to keyword/semantic matching
3. Uses LLM-assisted classification when others fail
4. Provides confidence scores that actually reach thresholds

The goal: NEVER get stuck in ISSUE_BUILDING if the user clearly describes a problem.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of smart classification."""
    issue_label: Optional[str]
    call_type_code: Optional[int]
    confidence: float
    method: str  # "direct_match", "keyword", "semantic", "llm", "none"
    matched_pattern: Optional[str] = None


# =============================================================================
# DIRECT PATTERN MATCHING - High confidence for unambiguous issues
# =============================================================================
# These patterns should ALWAYS match with high confidence (0.85+)
# Format: (pattern_regex, call_type_code, issue_label, confidence)

DIRECT_PATTERNS: List[Tuple[str, str, str, float]] = [
    # ── WATER ─────────────────────────────────────────────────────────────
    # 10020 LEAK/MAINT, 10035 MAJOR BURST, 10016 NO WATER, 10008 LOW PRESSURE
    # 10037 WATER CONTAMINATION, 10026 MAIN BLOCK, 10052 FIRE SERVICE PIPE
    # 10066 FAULTY METER, 10032 AREA OUTAGE, 10027 MANHOLE COVER MISSING
    (r"\b(water\s*leak|leaking\s*water|leak.*water)\b", "10020", "Leak/Maint", 0.90),
    (r"\bwater\s+(is\s+)?leaking\b", "10020", "Leak/Maint", 0.90),
    (r"\b(pipe|tap|faucet)\s+(is\s+)?leaking\b", "10020", "Leak/Maint", 0.88),
    (r"\bleaking\s+(pipe|water|tap)\b", "10020", "Leak/Maint", 0.88),
    (r"\b(burst\s*pipe|pipe\s*burst|burst.*water|water.*burst)\b", "10035", "Major Burst", 0.92),
    (r"\bno\s*water\b", "10016", "No Water", 0.88),
    (r"\b(low\s*(water\s*)?pressure|water\s*pressure\s*(is\s*)?(low|weak))\b", "10008", "Low Pressure", 0.88),
    (r"\b(brown|dirty|discolored?|smelly|smell)\s*(water|tap)\b", "10037", "Water Contamination", 0.88),
    (r"\b(water|tap)\s*(is\s*)?(brown|dirty|discolored?|smelly)\b", "10037", "Water Contamination", 0.88),
    (r"\b(sewer|sewage)\s*(blocked?|overflow|backup|problem)\b", "10026", "Main Block", 0.90),
    (r"\b(blocked?|overflowing?)\s*(sewer|drain|sewage)\b", "10026", "Main Block", 0.90),
    (r"\b(fire\s*)?hydrant\s*(leak|broken|damaged)\b", "10052", "Fire Service Pipe", 0.88),
    (r"\b(water\s*)?meter\s+(is\s+|was\s+)?(fault|faulty|broken|damaged|not\s*working|problem|malfunction)\b", "10066", "Faulty Meter", 0.87),
    (r"\bfaulty\s+(water\s+)?meter\b", "10066", "Faulty Meter", 0.87),
    (r"\b(water\s*)?meter\s+(fault|broken|problem|not\s*working)\b", "10066", "Faulty Meter", 0.85),
    (r"\b(area|whole area|entire area|neighborhood|street|block)\s+(no water|water outage|outage|has no water)\b", "10032", "Area Outage", 0.92),
    (r"\b(whole|entire)\s+(street|area|neighborhood|block)\s+.{0,20}no water\b", "10032", "Area Outage", 0.90),
    (r"\bno\s+water\s+(in|on)\s+(the\s+)?(whole|entire)\s+(area|street|neighborhood|block)\b", "10032", "Area Outage", 0.92),
    (r"\barea\s*wide\s+(water\s+)?(outage|no water)\b", "10032", "Area Outage", 0.90),
    (r"\bmanhole\s+(cover\s+)?(missing|gone|stolen|open|uncovered)\b", "10027", "Manhole Cover Missing", 0.88),
    (r"\b(open|uncovered|exposed)\s+manhole\b", "10027", "Manhole Cover Missing", 0.88),
    (r"\bmanhole\s+cover\s+(is|was)\s+(missing|stolen|gone)\b", "10027", "Manhole Cover Missing", 0.88),
    (r"\bno\s+cover\s+on\s+(the\s+)?manhole\b", "10027", "Manhole Cover Missing", 0.88),
    (r"\b(missing|stolen)\s+manhole\s+cover\b", "10027", "Manhole Cover Missing", 0.88),

    # ── ELECTRICITY ───────────────────────────────────────────────────────
    # 20021 NO SUPPLY, 20026 POWER OFF, 20028 LIGHTS OFF-HIGHWAY
    # 20006 FLICKERING SUPPLY, 20012 SPARKS AT POLE, 20005 EXPOSED WIRES
    # 20009 METER STOLEN, 20034 METER BROKEN, 20013 SUBSTATION BURNING
    # 20017 ILLEGAL CONN., 70001 TREES IN POWER LINE, 70065 TREE FALLEN INTO POWER LINE
    (r"\b(power\s*outage|power\s*(is\s*)?out|no\s+(power|electricity)|electricity\s*(is\s*)?out|power\s*cut)\b", "20021", "No Supply", 0.92),
    (r"\bblackout\b", "20021", "No Supply", 0.92),
    (r"\b(having|got|have|there.?s)\s*(a\s*)?(power\s*outage|power\s*cut|blackout)\b", "20021", "No Supply", 0.90),
    (r"\b(street\s*light|streetlight|lamp\s*post)\s*(out|off|broken|not\s*working|damaged)\b", "20028", "Lights Off-Highway", 0.92),
    (r"\b(light|lights)\s*(on\s*(my|the|our)\s*)?(street|road)\s*(out|off|broken|not\s*working)\b", "20028", "Lights Off-Highway", 0.88),
    (r"\b(the\s*)?street\s*light\s*(on\s*(my|the|our)\s*)?road\b", "20028", "Lights Off-Highway", 0.85),
    (r"\b(flickering|flicker)\s*(light|power|electricity)\b", "20006", "Flickering Supply", 0.85),
    (r"\b(sparking|spark)\s*(cable|wire|pole)\b", "20012", "Sparks At Pole", 0.92),
    (r"\b(electric|electrical)\s*(cable|cables|wire|wires|line|lines)\s*(on|in|lying|laying)\s*(the\s*)?(road|street|ground|pavement)\b", "20005", "Exposed Wires", 0.90),
    (r"\b(exposed|loose|hanging|down|fallen)\s*(electric|electrical|power)?\s*(cable|cables|wire|wires|line|lines)\b", "20005", "Exposed Wires", 0.88),
    (r"\b(cable|cables|wire|wires|line|lines)\s*(on|in|lying|laying)\s*(the\s*)?(road|street|ground)\b", "20005", "Exposed Wires", 0.85),
    (r"\b(electric|electrical)\s*(cable|cables|wire|wires)\b", "20005", "Exposed Wires", 0.82),
    (r"\b(cable|wire)\s*(theft|stolen|missing)\b", "20009", "Meter Stolen", 0.90),
    (r"\b(electricity|electric|power)\s*meter\s*(fault|broken|problem)\b", "20034", "Meter Broken", 0.85),
    (r"\btransformer\s*(fault|blown|problem|fire)\b", "20013", "Substation Burning", 0.88),
    (r"\btraffic\s*light\s*(out|off|broken|not\s*working|fault)\b", "60009", "Erratic Traffic Signal", 0.90),
    (r"\b(illegal|unauthorized|stealing)\s+(electricity|power)\b", "20017", "Illegal Conn.", 0.88),
    (r"\b(electricity|power)\s+(theft|stealing|illegal connection)\b", "20017", "Illegal Conn.", 0.88),
    (r"\b(tree|trees|branches|vegetation)\s+(touching|growing|near|into)\s+(power|electricity)\s+(line|lines|cable|wire)s?\b", "70001", "Trees In Power Line", 0.88),
    (r"\b(tree|branch)\w*\s+(on|against|near)\s+(power|electricity)\s+(line|cable)s?\b", "70001", "Trees In Power Line", 0.85),
    (r"\btrees\s+growing\s+into\s+power\s+lines\b", "70001", "Trees In Power Line", 0.88),
    (r"\b(tree|branch)\s+(fell|fallen|knocked)\s+(on|onto|into|down)\s+(power|electricity)\s+(line|cable|wire)s?\b", "70065", "Tree Fallen Into Power Line", 0.92),
    (r"\bpower\s+(line|lines)\s+down\s+.{0,20}tree\b", "70065", "Tree Fallen Into Power Line", 0.92),
    (r"\b(tree|branch)\s+(brought|took|knocked)\s+down\s+(power|electricity)\s+(line|cable)s?\b", "70065", "Tree Fallen Into Power Line", 0.90),

    # ── ROADS ─────────────────────────────────────────────────────────────
    # 60042 ROAD SUBSIDING, 60009 ERRATIC TRAFFIC SIGNAL, 60032 MISSING TRAFFIC SIGNS
    # 90002 FLOODING, 60001 BLOCKED KERB INLET, 60003 ROAD GRADING, 70008 TRAFFIC OBSTRUCTION
    (r"\b(pothole|pot\s*hole)s?\b", "60042", "Road Subsiding", 0.88),
    (r"\b(sinkhole|sink\s*hole)s?\b", "60042", "Road Subsiding", 0.90),
    (r"\btraffic\s*(light|signal|robot)\s*(not\s*working|broken|out|fault)\b", "60009", "Erratic Traffic Signal", 0.90),
    (r"\b(road\s*)?sign\s*(damaged|broken|missing|vandalized)\b", "60032", "Missing Traffic Signs", 0.85),
    (r"\b(road|street)\s*(flood|flooding|flooded)\b", "90002", "Flooding", 0.88),
    (r"\b(storm\s*)?drain\s*(blocked?|clogged?)\b", "60001", "Blocked Kerb Inlet", 0.88),
    (r"\b(blocked?|clogged?)\s*(storm\s*)?drain\b", "60001", "Blocked Kerb Inlet", 0.88),
    (r"\b(gravel|dirt|unpaved)\s+road\s+(uneven|bumpy|rough|ruts|needs leveling|needs grading)\b", "60003", "Road Grading", 0.85),
    (r"\b(uneven|bumpy|rough)\s+(gravel|dirt|unpaved)\s+road\b", "60003", "Road Grading", 0.85),
    (r"\bruts\s+in\s+(the\s+)?road\b", "60003", "Road Grading", 0.83),
    (r"\b(gravel|dirt)\s+road\s+needs\s+grading\b", "60003", "Road Grading", 0.85),
    (r"\b(traffic|road|street)\s+(is\s+)?(blocked|obstruction|blocking|obstructed)\b", "70008", "Traffic Obstruction", 0.88),
    (r"\b(blocking|obstructing)\s+(traffic|road|street)\b", "70008", "Traffic Obstruction", 0.88),
    (r"\b(debris|obstruction)\s+(in|on|blocking)\s+(the\s+)?(road|street)\b", "70008", "Traffic Obstruction", 0.85),

    # ── WASTE ─────────────────────────────────────────────────────────────
    # 30019 MISSED COLLECTION, 30024 BIN NOT COLLECTED, 30021 ILLEGAL DUMPING
    # 30013 NEW BIN(DOM), 30006 DEAD ANIMAL REMOVAL
    (r"\b(bin|refuse|garbage|rubbish)\s*(not\s*)?(collected?|picked?\s*up|missed)\b", "30019", "Missed Collection", 0.90),
    (r"\b(missed|no)\s*(bin|refuse|garbage)\s*collection\b", "30019", "Missed Collection", 0.90),
    (r"\b(illegal|fly)\s*(dump|dumping|tipping)\b", "30021", "Illegal Dumping", 0.90),
    (r"\breport(ing|ed)?\s+(illegal\s+)?(dump|dumping|tipping)\b", "30021", "Illegal Dumping", 0.90),
    (r"\b(dump|dumped?|tipped?)\s*(rubbish|waste|garbage|trash)\b", "30021", "Illegal Dumping", 0.88),
    (r"\b(rubbish|garbage|waste)\s*(dump|dumped?|on\s*(the\s*)?(pavement|street|land|property))\b", "30021", "Illegal Dumping", 0.88),
    (r"\b(unauthorized|unlawful)\s+(waste|rubbish|dumping)\b", "30021", "Illegal Dumping", 0.88),
    (r"\b(bin|rubbish|garbage)\s*(overflow|overflowing|full)\b", "30024", "Bin Not Collected", 0.88),
    (r"\b(overflow|overflowing)\s*(bin|rubbish)\b", "30024", "Bin Not Collected", 0.88),
    (r"\b(need|request|want)\s*(a\s*)?(new\s*)?bin\b", "30013", "New Bin(Dom)", 0.85),
    (r"\b(dead|carcass)\s*(animal|dog|cat)\b", "30006", "Dead Animal Removal", 0.88),

    # ── EMERGENCY ─────────────────────────────────────────────────────────
    # 90001 FIRE, 90002 FLOODING, 90003 VEHICLE ACCIDENT
    (r"\b(fire|burning|flames?)\s*(emergency)?\b", "90001", "Fire", 0.90),
    (r"\bsmoke\s*(from|sighting|visible)\b", "90001", "Fire", 0.85),
    (r"\b(car|vehicle)\s*(accident|crash)\b", "90003", "Vehicle Accident", 0.88),

    # ── ENVIRONMENTAL HEALTH ──────────────────────────────────────────────
    # 40074 AIR QUALITY, 90005 NOISE COMPLAINTS, 40065 UNHYGIENIC CONDITIONS
    # 40072 PEST INFESTATION COMPLAINT
    (r"\b(air\s*)?pollution\b", "40074", "Air Quality", 0.80),
    (r"\bnoise\s*(complaint|problem|nuisance)\b", "90005", "Noise Complaints", 0.85),
    (r"\b(health|safety|environmental)\s+hazard\b", "40065", "Unhygienic Conditions", 0.80),
    (r"\bhazardous\s+(substance|material|waste|condition)\b", "40065", "Unhygienic Conditions", 0.80),
    (r"\b(pest|rat|rodent|cockroach)\s*(infestation|problem)\b", "40072", "Pest Infestation Complaint", 0.88),

    # ── PARKS / TREES ─────────────────────────────────────────────────────
    # 70011 FALLEN TREES/BRANCHES, 70022 ARTERIAL GRASS CUTTING
    (r"\b(fallen|down)\s*tree\b", "70011", "Fallen Trees/Branches", 0.88),
    (r"\btree\s*(fallen|down|blocking)\b", "70011", "Fallen Trees/Branches", 0.88),
    (r"\b(dangerous|leaning)\s*tree\b", "70011", "Fallen Trees/Branches", 0.82),
    (r"\b(tree|branch)\s+(fell|fallen|down)\s+(on|onto|blocking)\s+(the\s+)?(road|street|power|line)\b", "70011", "Fallen Trees/Branches", 0.92),
    (r"\b(fallen|down)\s+(tree|branch|branches)\s+.{0,20}(blocking|on)\s+(road|street)\b", "70011", "Fallen Trees/Branches", 0.90),
    (r"\btree\s+fell\s+on\s+(the\s+)?road\b", "70011", "Fallen Trees/Branches", 0.92),
    (r"\b(overgrown|tall)\s*(grass|vegetation|weeds)\b", "70022", "Arterial Grass Cutting", 0.82),

    # ── BILLING ───────────────────────────────────────────────────────────
    # 50037 RATES TARIFF/CHARGE, 50014 PAYMENT ENQUIRY
    (r"\b(bill|billing|invoice)\s*(query|question|problem|wrong)\b", "50037", "Rates Tariff/Charge", 0.85),
    (r"\b(account|payment)\s*(issue|problem|query)\b", "50014", "Payment Enquiry", 0.82),

    # ── TRANSPORT ─────────────────────────────────────────────────────────
    # 25032 DAMAGED BUS STOP, 80027 NO STOPPING, 25010 LOST TRIPS
    # 80029 RECKLESS DRIVING, 25019 DRIVER BEHAVIOUR
    (r"\bbus\s*stop\s*(damaged|broken|vandalized)\b", "25032", "Damaged Bus Stop", 0.85),
    (r"\b(bus|buses)\s+(not\s+|didn'?t\s+|never\s+|wouldn'?t\s+)?(stop|stopping|stopped)\b", "80027", "No Stopping", 0.90),
    (r"\b(bus|buses)\s+(drove\s+past|passed\s+by|skipped|missed)\s+(stop|me|us)?\b", "80027", "No Stopping", 0.88),
    (r"\bbus\s+.{0,20}(not\s+stopping|won'?t\s+stop|never\s+stops)\b", "80027", "No Stopping", 0.88),
    (r"\b(bus|buses)\s*(schedule|route|timing)\s*(issue|problem)\b", "25010", "Lost Trips", 0.82),
    (r"\b(bus|buses)\s+(is\s+)?(arriv\w*|running|coming)\s+(late|behind|delayed)\b", "25010", "Lost Trips", 0.85),
    (r"\b(late|delayed)\s+(bus|buses|arrival)\b", "25010", "Lost Trips", 0.82),
    (r"\b(bus|buses)\s+(not\s+)?(on\s+time|delayed|late)\b", "25010", "Lost Trips", 0.80),
    (r"\b(reckless|dangerous|unsafe|careless)\s+(driv|driver)\w*\b", "80029", "Reckless Driving", 0.90),
    (r"\b(driv|driver)\w*\s+(is\s*)?(reckless|dangerous|unsafe|careless)\b", "80029", "Reckless Driving", 0.90),
    (r"\b(aggressive|crazy|bad)\s+(driv|driver)\w*\b", "80029", "Reckless Driving", 0.85),
    (r"\b(driv|driver)\w*\s+(is\s*)?(aggressive|crazy|bad|speeding)\b", "80029", "Reckless Driving", 0.85),
    (r"\b(driv|driver)\w*\s+(is\s*)?(sleep|asleep|sleeping|drowsy|dozing|nodding off)\b", "80029", "Reckless Driving - Sleeping Driver", 0.95),
    (r"\b(sleep|asleep|sleeping|drowsy|dozing)\s+(while|when)\s+(driv|behind the wheel)\w*\b", "80029", "Reckless Driving - Sleeping Driver", 0.95),
    (r"\b(bus|taxi)\s+driver\s+(is\s*)?(sleep|asleep|sleeping|drowsy)\w*\b", "80029", "Reckless Driving - Sleeping Driver", 0.95),
    (r"\b(fall|fell|falling)\s+asleep\s+(while\s+)?(driv|at the wheel|behind wheel)\w*\b", "80029", "Reckless Driving - Sleeping Driver", 0.93),
    (r"\b(bus|taxi|metrobus|driver)\s+(driver\s+)?(is\s*)?(misbehav)\w*\b", "25019", "Driver Behaviour", 0.55),
    (r"\b(driv|driver)\w*\s+(is\s*)?(misbehav)\w*\b", "25019", "Driver Behaviour", 0.55),
    # verb + adjective: "driver is rude", "driver was rude", "driver being rude"
    (r"\b(driv|driver)\w*\s+(is|was|being)\s+(rude|inappropriate|unprofessional|hostile|refusing|mean|nasty|impolite)\w*\b", "25019", "Driver Behaviour", 0.88),
    # verb chain: "driver is being rude"
    (r"\b(driv|driver)\w*\s+(is|was)\s+being\s+(rude|inappropriate|unprofessional|hostile|mean|nasty|impolite)\w*\b", "25019", "Driver Behaviour", 0.90),
    # adjective directly follows noun without verb: "driver rude", "bus driver rude"
    (r"\b(driv|driver)\w*\s+(rude|inappropriate|unprofessional|hostile|mean|nasty|impolite|abusive|disrespectful)\b", "25019", "Driver Behaviour", 0.85),
    (r"\b(bus|taxi)\s+driver\s+(rude|inappropriate|hostile|mean|nasty|abusive|disrespectful|unprofessional)\b", "25019", "Driver Behaviour", 0.87),
    # adjective before noun: "rude driver", "abusive driver"
    (r"\b(rude|inappropriate|unprofessional|hostile|abusive|mean|nasty|impolite)\s+(driv|driver)\w*\b", "25019", "Driver Behaviour", 0.88),
    (r"\b(bus|taxi)\s+driver\s+(is|was|being)\s+(rude|inappropriate|hostile|refusing|mean|nasty)\w*\b", "25019", "Driver Behaviour", 0.90),
    (r"\breckless\s*driving\b", "80029", "Reckless Driving", 0.92),
    (r"\bdangerous\s*driving\b", "80029", "Reckless Driving", 0.90),
    (r"\b(bus|taxi|metrobus|rea\s*vaya)\s+(driver|driv\w+)\s+(is\s*)?(reckless|dangerous|driving\s+(reckless|dangerous))\b", "80029", "Reckless Driving", 0.92),
    (r"\b(reckless|dangerous)\s+(bus|taxi|metrobus|rea\s*vaya)\s+(driver|driv\w+)\b", "80029", "Reckless Driving", 0.92),
    (r"\bdriving\s+(recklessly|dangerously|carelessly|aggressively)\b", "80029", "Reckless Driving", 0.90),
    (r"\b(driver|bus|taxi)\s+driving\s+(recklessly|dangerously)\b", "80029", "Reckless Driving", 0.90),
    (r"\b(bus|taxi)\s+driver\s+driving\s+(recklessly|dangerously|badly)\b", "80029", "Reckless Driving", 0.92),
    (r"\b(speeding|overtaking|swerving)\s+(bus|taxi|driver)\b", "80029", "Reckless Driving", 0.85),
    (r"\b(bus|taxi)\s+(speeding|overtaking dangerously|running red)\b", "80029", "Reckless Driving", 0.85),
]


def _normalize_text(text: str) -> str:
    """Normalize text for matching."""
    # Convert to lowercase
    text = text.lower()
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Keep apostrophes but remove other special chars
    text = re.sub(r"[^\w\s']", ' ', text)
    return text


def is_too_vague(text: str) -> bool:
    """
    Check if input is too vague for classification.
    Vague inputs include:
    - Just domain keywords ("electricity", "water", "roads")
    - Generic problem words without specifics ("issue", "problem", "fault")
    - Very short inputs (1-2 words without problem indicators)
    
    Returns True if vague (should ask for clarification)
    """
    text_lower = text.lower().strip()
    words = text_lower.split()

    # Single domain words that are always vague on their own
    domain_words = {
        'water', 'electricity', 'electric', 'power', 'roads', 'road',
        'waste', 'rubbish', 'refuse', 'garbage', 'trash', 'sewer',
        'sewerage', 'billing', 'traffic', 'transport', 'bus', 'metro',
        'taxi', 'train', 'street', 'light', 'rates',
    }

    # Multi-word phrases that are domain-only (no specific problem described)
    domain_phrases = {
        'metro bus', 'city power', 'street light', 'street lights',
        'road maintenance', 'waste collection', 'public transport',
        'my water', 'my electricity', 'my power', 'my roads',
    }

    # Single word inputs are vague
    if len(words) == 1:
        return True

    # Exact multi-word domain phrases
    if text_lower in domain_phrases:
        return True

    # 2-3 word inputs where every word is a domain word (e.g. "metro bus")
    if len(words) <= 3 and all(w in domain_words for w in words):
        return True

    # Check for domain-only inputs (just mentioning a service area)
    domain_only_patterns = [
        r"^\s*(water|electricity|electric|power|roads?|waste|refuse|garbage|trash|billing|traffic|metro|bus|transport)\s*(issue|problem|fault|concern|query|question)?s?\s*$",
        r"^\s*(my|the|our|i\s+have)\s+(water|electricity|power|roads?|metro\s+bus|bus|transport)\s*(issue|problem|fault|concern)s?\s*$",
        r"^\s*(issue|problem|fault)\s+with\s+(water|electricity|power|roads?|waste|metro\s+bus|bus|transport)\s*$",
    ]

    if any(re.match(pattern, text_lower) for pattern in domain_only_patterns):
        return True

    # Check if it's a generic complaint without specifics
    generic_complaints = [
        r"^\s*(electricity|power|water|roads?|metro\s+bus|bus|transport)\s+(not\s+working|issues?|problems?|faults?)\s*$",
        r"^\s*(my|the|our)\s+(electricity|power|water|roads?|bus|transport)\s+(is|are)\s+(not\s+working|broken|bad)\s*$",
    ]

    if any(re.match(pattern, text_lower) for pattern in generic_complaints):
        return True

    return False


def direct_pattern_match(text: str) -> Optional[ClassificationResult]:
    """
    Try to match the user text against direct patterns.
    Returns high-confidence result if a clear match is found.
    
    CRITICAL: This checks for vagueness FIRST before attempting pattern matching.
    """
    # CRITICAL: Check if input is too vague BEFORE pattern matching
    # Vague inputs should NOT trigger classification - they need clarification
    if is_too_vague(text):
        logger.info(f"Skipping pattern match - input is too vague: '{text[:50]}...'")
        return None
    
    normalized = _normalize_text(text)
    
    best_match: Optional[ClassificationResult] = None
    best_confidence = 0.0
    
    for pattern, code, label, confidence in DIRECT_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            if confidence > best_confidence:
                best_confidence = confidence
                # Convert code to int
                try:
                    code_int = int(code)
                except (ValueError, TypeError):
                    code_int = None
                    
                best_match = ClassificationResult(
                    issue_label=label,
                    call_type_code=code_int,
                    confidence=confidence,
                    method="direct_match",
                    matched_pattern=pattern
                )
    
    if best_match:
        logger.info(f"Direct pattern match: '{best_match.issue_label}' (conf={best_match.confidence})")
    
    return best_match


# =============================================================================
# PHRASE EXTRACTION - Extract key problem phrases from user text
# =============================================================================

PROBLEM_PHRASES = [
    # Water
    "water leak", "leaking water", "burst pipe", "pipe burst", "no water", 
    "low water pressure", "low pressure", "brown water", "dirty water", 
    "smelly water", "sewer blocked", "blocked sewer", "drain blocked",
    "sewage overflow", "fire hydrant", "water meter",
    
    # Electricity
    "power outage", "no power", "no electricity", "blackout", "power cut",
    "street light", "streetlight", "light not working", "flickering lights",
    "sparking cable", "cable theft", "stolen cable", "transformer", 
    "electricity meter", "traffic light", "traffic signal",
    
    # Roads
    "pothole", "sinkhole", "road sign", "road flooding", "flooded road",
    "pavement damage", "storm drain", "blocked drain",
    
    # Waste
    "bin not collected", "missed collection", "refuse collection",
    "illegal dumping", "rubbish dumped", "overflowing bin", "dead animal",
    
    # Emergency
    "fire", "smoke", "medical emergency", "ambulance", "car accident",
    
    # Other
    "noise complaint", "pest infestation", "fallen tree", "dangerous tree",
    "billing query", "account issue", "bus stop",
]


def extract_problem_phrases(text: str) -> List[str]:
    """Extract problem-related phrases from user text."""
    text_lower = text.lower()
    found = []
    for phrase in PROBLEM_PHRASES:
        if phrase in text_lower:
            found.append(phrase)
    return found


# =============================================================================
# LLM-ASSISTED CLASSIFICATION
# =============================================================================

def llm_classify(text: str, conversation_history: Optional[List[str]] = None) -> Optional[ClassificationResult]:
    """
    Use LLM to classify when pattern matching fails.
    This is a fallback that should provide reasonable classification
    even for unusual phrasings.
    
    CRITICAL: Also checks for vagueness - LLM should not classify vague inputs either!
    """
    # CRITICAL: Don't let LLM classify vague inputs either
    if is_too_vague(text):
        logger.info(f"LLM classification skipped - input is too vague: '{text[:50]}...'")
        return None
    
    try:
        from src.core.dspy_pipeline import context_analyzer
    except ImportError:
        logger.warning("DSPy pipeline not available for LLM classification")
        return None
    
    # Build context from conversation history
    context = text
    if conversation_history:
        context = " ".join(conversation_history[-3:]) + " " + text
    
    try:
        result = context_analyzer(user_story=context)
        
        # Map the LLM understanding to a call type
        extracted_issue = getattr(result, 'extracted_issue', '') or ''
        is_municipal = getattr(result, 'is_municipal', 'no') == 'yes'
        confidence_label = getattr(result, 'confidence', 'low')
        
        # DETAILED LOGGING for debugging
        logger.info(f"LLM extraction: issue='{extracted_issue}', municipal={is_municipal}, conf={confidence_label}")
        
        # Map confidence label to score
        conf_map = {'high': 0.75, 'medium': 0.55, 'low': 0.35}
        confidence = conf_map.get(confidence_label, 0.35)
        
        # SPECIAL CASE: Driver issues are ALWAYS municipal (they're transport safety issues)
        # This prevents LLM from incorrectly marking driver issues as "not municipal"
        # Check BOTH the original text AND the extracted issue
        text_lower = text.lower()
        extracted_lower = extracted_issue.lower()
        
        has_driver_keyword = any(kw in text_lower for kw in ["driver", "driving", "bus driver", "taxi driver"]) or \
                            any(kw in extracted_lower for kw in ["driver", "driving", "bus driver", "taxi driver"])
        
        has_safety_concern = any(concern in text_lower for concern in ["smoking", "phone", "texting", "sleeping", 
                                                                        "reckless", "unsafe", "speeding", "dangerous",
                                                                        "failing to stop", "safety risk"]) or \
                            any(concern in extracted_lower for concern in ["smoking", "phone", "texting", "sleeping",
                                                                          "reckless", "unsafe", "speeding", "dangerous",
                                                                          "failing to stop", "safety risk"])
        
        if has_driver_keyword and has_safety_concern:
            logger.info(f"LLM: Forcing is_municipal=True for driver safety issue (found in text or extraction)")
            is_municipal = True
        
        # Only proceed if municipal issue
        if not is_municipal:
            logger.info(f"LLM: Skipping - not a municipal issue")
            return None
        
        # Try to map extracted issue to a call type
        issue_lower = extracted_issue.lower()
        
        # Expanded keyword-based mapping for LLM classification fallback
        llm_mappings = [
            # Water issues
            (["water leak", "leak", "leaking", "drip"], "10002", "Water Leak"),
            (["burst pipe", "burst", "gushing", "flooding pipe"], "10003", "Burst Pipe"),
            (["no water", "no supply", "dry tap", "water cut"], "10005", "No Water Supply"),
            (["low pressure", "weak pressure", "trickle"], "10007", "Low Water Pressure"),
            (["brown water", "dirty water", "quality", "smelly water", "discolored"], "10009", "Water Quality Issue"),
            (["sewer", "sewage", "drain blocked", "clogged drain"], "10011", "Sewer Blockage"),
            (["hydrant", "fire hydrant"], "10015", "Fire Hydrant Issue"),
            (["water meter", "meter fault"], "10017", "Water Meter Fault"),
            # Electricity issues
            (["power out", "no power", "blackout", "outage", "power cut"], "11001", "Power Outage"),
            (["street light", "lamp post", "light not working", "dark street"], "11003", "Street Light Fault"),
            (["flickering", "flicker", "unstable power"], "11005", "Flickering Power"),
            (["sparking", "spark", "exposed cable", "cable down", "wire"], "11007", "Sparking Cable"),
            (["cable theft", "stolen cable", "missing cable"], "11009", "Cable Theft"),
            (["electricity meter", "prepaid meter"], "11011", "Electricity Meter Fault"),
            (["transformer", "substation"], "11013", "Transformer Issue"),
            # Road issues
            (["pothole", "hole in road"], "12001", "Pothole"),
            (["sinkhole", "road collapse"], "12003", "Sinkhole"),
            (["traffic light", "traffic signal", "robot"], "12005", "Traffic Light Fault"),
            (["road sign", "sign damaged", "missing sign"], "12007", "Road Sign Damaged"),
            (["road flood", "flooded road", "water on road"], "12009", "Road Flooding"),
            (["pavement", "sidewalk", "cracked pavement"], "12011", "Pavement Damage"),
            (["storm drain", "blocked drain", "drain cover"], "12013", "Blocked Storm Drain"),
            # Waste issues
            (["bin", "refuse", "collection", "not collected", "missed pickup"], "13001", "Missed Refuse Collection"),
            (["dump", "rubbish", "illegal dumping", "fly tipping"], "13003", "Illegal Dumping"),
            (["overflow", "overflowing bin", "full bin"], "13005", "Overflowing Bin"),
            (["new bin", "need bin", "replace bin"], "13007", "Request New Bin"),
            (["dead animal", "carcass", "roadkill"], "13009", "Dead Animal Removal"),
            # Emergency
            (["fire", "burning", "flames"], "14001", "Fire Emergency"),
            (["smoke", "smoke sighting"], "14003", "Smoke Sighting"),
            (["medical", "ambulance", "emergency medical"], "14005", "Medical Emergency"),
            (["accident", "crash", "collision"], "14007", "Vehicle Accident"),
            # Environmental
            (["pollution", "air quality"], "15001", "Air Pollution"),
            (["noise", "loud", "noise complaint"], "15003", "Noise Complaint"),
            (["hazard", "health hazard"], "15005", "Health Hazard"),
            (["pest", "rat", "rodent", "cockroach"], "15007", "Pest Infestation"),
            # Parks/Trees
            (["fallen tree", "tree down", "tree blocking"], "16001", "Fallen Tree"),
            (["dangerous tree", "leaning tree"], "16003", "Dangerous Tree"),
            (["overgrown", "tall grass", "weeds"], "16007", "Overgrown Vegetation"),
            # Transport
            (["bus stop", "shelter damaged"], "18001", "Bus Stop Damaged"),
            (["dirty bus", "dirty seat", "unclean vehicle"], "18005", "Dirty Bus Seats"),
            # DRIVER ISSUES - Specific behaviors (still use keyword matching for known issues)
            (["reckless", "dangerous driving", "bad driver", "sleeping", "asleep", "drowsy"], "80029", "Reckless Driving"),
            # Billing
            (["bill", "billing", "invoice", "account"], "17001", "Billing Query"),
        ]
        
        # SMART DRIVER ISSUE DETECTION
        # Distinguish between SAFETY issues (80029) vs BEHAVIOR issues (25019)
        # CRITICAL: Only if "driver" is explicitly in ORIGINAL TEXT - don't trust LLM inference
        driver_keywords = ["driver", "driving", "taxi driver", "bus driver"]
        
        # SAFETY concerns → 80029 (Reckless Driving)
        safety_keywords = ["smoking", "phone", "texting", "drinking", "eating", 
                          "not stopping", "failing to stop", "didn't stop", "not stop", "ran through",
                          "speeding", "running red", "ran red", "run red light", 
                          "unsafe", "distracted", "watching", "looking at",
                          "safety risk", "danger", "asleep", "sleeping", "drowsy"]
        
        # BEHAVIOR/ATTITUDE concerns → 25019 (Driver Behaviour)
        behavior_keywords = ["rude", "hostile", "inappropriate", "unprofessional", 
                            "refusing", "impolite", "mean", "nasty", "abusive",
                            "misbehaving", "bad attitude", "complaint"]
        
        text_lower = text.lower()
        # ONLY check original text - don't trust LLM extraction which might infer "driver" incorrectly
        has_driver = any(kw in text_lower for kw in driver_keywords)
        has_safety_concern = any(kw in text_lower for kw in safety_keywords)
        has_behavior_concern = any(kw in text_lower for kw in behavior_keywords)
        
        if has_driver and has_safety_concern:
            logger.info(f"LLM: Detected driver SAFETY issue in '{text}' → 80029 Reckless Driving")
            try:
                return ClassificationResult(
                    issue_label="Reckless Driving",
                    call_type_code=80029,
                    confidence=min(confidence + 0.20, 0.75),
                    method="llm",
                    matched_pattern=f"driver+safety: {text}"
                )
            except (ValueError, TypeError):
                logger.warning(f"LLM: Failed to create ClassificationResult for driver safety issue")
                pass
        
        if has_driver and has_behavior_concern:
            logger.info(f"LLM: Detected driver BEHAVIOR issue in '{text}' → 25019 Driver Behaviour")
            try:
                return ClassificationResult(
                    issue_label="Driver Behaviour",
                    call_type_code=25019,
                    confidence=min(confidence + 0.20, 0.75),
                    method="llm",
                    matched_pattern=f"driver+behavior: {text}"
                )
            except (ValueError, TypeError):
                logger.warning(f"LLM: Failed to create ClassificationResult for driver behavior issue")
                pass
        
        for keywords, code, label in llm_mappings:
            if any(kw in issue_lower for kw in keywords):
                try:
                    code_int = int(code)
                except (ValueError, TypeError):
                    code_int = None
                    
                return ClassificationResult(
                    issue_label=label,
                    call_type_code=code_int,
                    confidence=confidence,
                    method="llm",
                    matched_pattern=f"LLM: {extracted_issue}"
                )
        
        # If we got here, LLM understood but we couldn't map it
        logger.info(f"LLM understood issue but couldn't map: {extracted_issue}")
        return None
        
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}")
        return None


# =============================================================================
# SMART CLASSIFIER - MAIN ENTRY POINT
# =============================================================================

def smart_classify(
    text: str,
    conversation_history: Optional[List[str]] = None,
    existing_classification: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Smart classification that tries multiple techniques:
    
    CRITICAL BEHAVIOR:
    - If input is vague (e.g., "electricity issues", "power problems"), returns low confidence
    - This ensures the chatbot asks for clarification instead of rushing to classification
    - CONFIRMATION DETECTION: If user confirms bot's question, boost confidence significantly
    
    Order of attempts:
    1. Confirmation detection (if user answering bot's question, boost confidence)
    2. Vagueness check (if vague, return low confidence immediately)
    3. Direct pattern matching (fastest, highest confidence)
    4. Existing keyword/semantic classification (if provided)
    5. LLM-assisted classification (fallback)
    
    Returns a classification dict compatible with the existing system:
    {
        "issue_label": str | None,
        "call_type_code": int | None,
        "confidence": float,
        "_smart_method": str  # For debugging
    }
    """
    # Handle empty/whitespace input explicitly
    if not text or not text.strip():
        return {
            "issue_label": None,
            "call_type_code": None,
            "confidence": 0.0,
            "_smart_method": "empty_input",
            "message": "Please repeat",
        }

    # Handle very short inputs (1-2 words) that are just domain words
    stripped = text.strip()
    text_lower = stripped.lower()
    word_count = len(stripped.split())
    if word_count <= 2 and text_lower in ["water", "electricity", "roads", "waste", "transport"]:
        return {
            "issue_label": None,
            "call_type_code": None,
            "confidence": 0.0,
            "_smart_method": "short_domain_only",
            "domain": text_lower,
            "needs_clarification": True,
        }

    # Step 0: CONFIRMATION DETECTION - Check if user is confirming bot's question
    # This is CRITICAL for multi-turn clarification flows
    text_lower = text.lower().strip()
    
    # Check if this looks like a confirmation response
    is_explicit_confirmation = text_lower.startswith(("yes", "yeah", "yep", "correct", "that's right", "exactly"))
    
    # Also check for implicit confirmation - user providing more detail on same topic
    # Example: Bot asks "are buses late?", user says "the buses arrive late" (no "yes" but still confirming)
    is_implicit_confirmation = False
    if existing_classification and conversation_history and len(conversation_history) >= 2:
        # Get last few user messages to see if there's topic continuity
        last_user_msg = conversation_history[-2] if len(conversation_history) >= 2 else ""
        last_user_msg_lower = last_user_msg.lower()
        
        # Check if current message shares keywords with previous context
        # This detects when user is elaborating on the same issue
        shared_keywords = []
        for keyword in ["bus", "buses", "schedule", "late", "delay", "arrive", "arrival", "metro", "transport"]:
            if keyword in text_lower and keyword in last_user_msg_lower:
                shared_keywords.append(keyword)
        
        if len(shared_keywords) >= 2:  # At least 2 shared keywords = same topic
            is_implicit_confirmation = True
            logger.info(f"Implicit confirmation detected: shared keywords {shared_keywords}")
    
    # If user is confirming, check if new input suggests SAME or DIFFERENT classification
    if (is_explicit_confirmation or is_implicit_confirmation) and existing_classification:
        existing_conf = existing_classification.get("confidence", 0) or 0
        existing_code = existing_classification.get("call_type_code")
        existing_label = existing_classification.get("issue_label", "")
        
        # Check if current input has a STRONGER classification that DIFFERS from existing
        current_direct_match = direct_pattern_match(text)
        
        if current_direct_match and current_direct_match.confidence > 0.70:
            # New input has strong match - check if it's DIFFERENT from existing
            if current_direct_match.call_type_code != existing_code:
                # New information suggests DIFFERENT issue - reclassify instead of boost
                logger.info(f"Smart classifier: New info suggests different issue ('{current_direct_match.issue_label}' vs '{existing_label}') - reclassifying")
                # Continue to normal classification flow (don't return here)
            else:
                # Same issue confirmed - boost it!
                boost_amount = 0.50 if is_explicit_confirmation else 0.35
                boosted_conf = min(0.85, max(existing_conf, current_direct_match.confidence) + boost_amount)
                logger.info(f"Smart classifier: Same issue confirmed! Boosting to {boosted_conf:.2f}")
                return {
                    "issue_label": current_direct_match.issue_label or existing_label,
                    "call_type_code": current_direct_match.call_type_code or existing_code,
                    "confidence": boosted_conf,
                    "_smart_method": "confirmation_boost_matched"
                }
        elif existing_code and existing_conf > 0.15:
            # No strong new match, but existing classification exists - boost if explicit "yes"
            if is_explicit_confirmation:
                boost_amount = 0.50
                boosted_conf = min(0.75, existing_conf + boost_amount)
                logger.info(f"Smart classifier: Explicit confirmation! Boosting conf from {existing_conf:.2f} to {boosted_conf:.2f}")
                return {
                    **existing_classification,
                    "confidence": boosted_conf,
                    "_smart_method": "confirmation_boost"
                }
    
    # Step 1: Check for vagueness (but not if confirming)
    if is_too_vague(text) and not (is_explicit_confirmation or is_implicit_confirmation):
        logger.info(f"Smart classifier: Input is too vague, returning low confidence: '{text[:50]}...'")
        return {
            "issue_label": None,
            "call_type_code": None,
            "confidence": 0.15,  # Very low confidence to trigger clarification
            "_smart_method": "vague_input"
        }
    
    # Step 1: Try direct pattern matching first
    direct_result = direct_pattern_match(text)
    if direct_result and direct_result.confidence >= 0.80:
        logger.info(f"Smart classifier: Direct match '{direct_result.issue_label}' ({direct_result.confidence})")
        return {
            "issue_label": direct_result.issue_label,
            "call_type_code": direct_result.call_type_code,
            "confidence": direct_result.confidence,
            "_smart_method": "direct_match",
            "_matched_pattern": direct_result.matched_pattern
        }
    
    # Step 2: Check existing classification (from keyword/semantic)
    if existing_classification:
        existing_conf = existing_classification.get("confidence", 0) or 0
        existing_code = existing_classification.get("call_type_code")
        
        # If existing classification is good enough, use it
        if existing_code and existing_conf >= 0.3:
            logger.info(f"Smart classifier: Using existing classification ({existing_conf})")
            return {
                **existing_classification,
                "_smart_method": "keyword_semantic"
            }
        
        # If direct match exists but is lower confidence, boost it with existing
        if direct_result:
            # Boost direct match confidence if existing classification agrees
            boosted_conf = max(direct_result.confidence, existing_conf + 0.1)
            if boosted_conf >= 0.3:
                return {
                    "issue_label": direct_result.issue_label,
                    "call_type_code": direct_result.call_type_code,
                    "confidence": min(boosted_conf, 0.95),
                    "_smart_method": "direct_boosted"
                }
    
    # Step 3: If direct match exists with moderate confidence, use it
    if direct_result and direct_result.confidence >= 0.5:
        return {
            "issue_label": direct_result.issue_label,
            "call_type_code": direct_result.call_type_code,
            "confidence": direct_result.confidence,
            "_smart_method": "direct_match",
            "_matched_pattern": direct_result.matched_pattern
        }
    
    # Step 4: Try LLM classification
    llm_result = llm_classify(text, conversation_history)
    if llm_result:
        # Use conditional threshold: 0.35 for driver issues (both safety and behavior), 0.4 for all others
        is_driver_issue = (llm_result.call_type_code in [80029, 25019] or 
                          (llm_result.issue_label and ("Reckless Driving" in llm_result.issue_label or 
                                                       "Driver Behaviour" in llm_result.issue_label)))
        threshold = 0.35 if is_driver_issue else 0.4
        
        if llm_result.confidence >= threshold:
            logger.info(f"Smart classifier: LLM match '{llm_result.issue_label}' ({llm_result.confidence}, threshold={threshold})")
            return {
                "issue_label": llm_result.issue_label,
                "call_type_code": llm_result.call_type_code,
                "confidence": llm_result.confidence,
                "_smart_method": "llm",
                "_matched_pattern": llm_result.matched_pattern
            }
        else:
            logger.info(f"Smart classifier: LLM result too low confidence ({llm_result.confidence} < {threshold}) - rejected")
    
    # Step 5: Use best available result with lowered confidence
    if direct_result:
        return {
            "issue_label": direct_result.issue_label,
            "call_type_code": direct_result.call_type_code,
            "confidence": direct_result.confidence * 0.8,  # Reduce confidence
            "_smart_method": "direct_fallback"
        }
    
    if existing_classification and existing_classification.get("call_type_code"):
        return {
            **existing_classification,
            "_smart_method": "keyword_fallback"
        }
    
    # No match found
    return {
        "issue_label": None,
        "call_type_code": None,
        "confidence": 0.0,
        "_smart_method": "none"
    }


__all__ = [
    "smart_classify",
    "direct_pattern_match",
    "extract_problem_phrases",
    "llm_classify",
    "ClassificationResult",
    "DIRECT_PATTERNS",
]
