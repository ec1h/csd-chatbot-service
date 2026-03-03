"""
Case Memory - Source of Truth
==============================
This is the append-only memory that tracks the case being built.
Messages are append-only. Issue and location change only via explicit user correction.

Progressive Issue Building:
- Tracks clarification attempts to prevent infinite loops
- Builds cumulative issue description from user statements
- Tracks what aspects have been clarified to avoid repeating questions

NEW BEHAVIOR CONTRACT SUPPORT:
- Top-N candidates tracking (all call types discoverable)
- Slot-based clarification for rare call types
- Domain tracking (domains ≠ issues)
- Topic switching detection
- Confidence-guided progression (low/medium/high bands)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Any


@dataclass
class CaseMemory:
    """Source of truth for the case being built."""
    messages: List[str] = field(default_factory=list)
    issue_summary: Optional[str] = None
    call_type_code: Optional[int] = None
    location: Optional[str] = None
    confirmed: bool = False
    # Progressive clarification fields (additive, safe to ignore for legacy flows)
    missing_slots: List[str] = field(default_factory=list)
    clarification_options: dict = field(default_factory=dict)
    last_intent_summary: Optional[str] = None

    # Progressive issue building fields
    clarification_count: int = 0  # How many times we've asked for clarification
    cumulative_issue: Optional[str] = None  # Built-up issue description
    asked_questions: List[str] = field(default_factory=list)  # Questions already asked (to avoid repeats)
    clarified_aspects: Set[str] = field(default_factory=set)  # What's been clarified: "location_type", "facility_type", etc.
    last_classification_confidence: float = 0.0  # Track if we're making progress

    # Simplified clarification: 3-strike rule (classification attempts without call type hit)
    classification_miss_count: int = 0  # Consecutive classification attempts with no call type
    we_dont_understand_offered: bool = False  # We've said "we don't understand" + asked LLM question once
    pending_location: Optional[str] = None  # Location-like input during issue building; use once we have call type
    
    # Correction mode: track when user rejected confirmation and is correcting
    in_correction_mode: bool = False  # User said "no" at confirmation and is providing corrections

    # NEW: Top-N Classification Support (Behavior Contract)
    candidate_call_types: List[Dict[str, Any]] = field(default_factory=list)  # Top candidates with confidence scores
    last_detected_domain: Optional[str] = None  # Last detected domain (water/electricity/roads/etc)
    domain_history: List[str] = field(default_factory=list)  # Track domain changes for topic switching detection
    
    # NEW: Confidence Bands (Low/Medium/High)
    confidence_band: str = "none"  # none, low, medium, high
    last_classification_method: Optional[str] = None  # direct_match, keyword, llm, etc.
    
    # NEW: Slot-based clarification
    required_slots: Dict[str, Any] = field(default_factory=dict)  # Slots needed for rare call types
    collected_slots: Dict[str, Any] = field(default_factory=dict)  # Slots collected from user

    def append_message(self, message: str) -> None:
        """Append a message to the conversation history (append-only)."""
        self.messages.append(message)

    def update_issue(self, issue_summary: str, call_type_code: Optional[int] = None) -> None:
        """Update issue information (only via explicit user correction)."""
        self.issue_summary = issue_summary
        if call_type_code is not None:
            self.call_type_code = call_type_code

    def update_location(self, location: str) -> None:
        """Update location (only via explicit user correction)."""
        self.location = location

    def confirm(self) -> None:
        """Mark the case as confirmed by the user."""
        self.confirmed = True

    def increment_clarification(self) -> int:
        """Increment clarification counter and return new count."""
        self.clarification_count += 1
        return self.clarification_count

    def record_asked_question(self, question_type: str) -> None:
        """Record that we asked a specific type of question."""
        if question_type not in self.asked_questions:
            self.asked_questions.append(question_type)

    def was_question_asked(self, question_type: str) -> bool:
        """Check if a question type was already asked."""
        return question_type in self.asked_questions

    def mark_aspect_clarified(self, aspect: str) -> None:
        """Mark an aspect as clarified (e.g., 'facility_type', 'severity')."""
        self.clarified_aspects.add(aspect)

    def is_aspect_clarified(self, aspect: str) -> bool:
        """Check if an aspect has been clarified."""
        return aspect in self.clarified_aspects

    def update_cumulative_issue(self, new_info: str) -> None:
        """
        Build up the issue description progressively.
        Merges new information with existing cumulative issue.
        """
        if not self.cumulative_issue:
            self.cumulative_issue = new_info
        else:
            # Merge: add new info that's not redundant
            self.cumulative_issue = f"{self.cumulative_issue}. {new_info}"

    def get_full_context(self) -> str:
        """
        Get the complete context for classification.
        Returns cumulative issue if built, otherwise joins all messages.
        """
        if self.cumulative_issue:
            return self.cumulative_issue
        return " ".join(self.messages)

    def should_force_classification(self, max_attempts: int = 2) -> bool:
        """
        Determine if we should force classification instead of asking more questions.
        Returns True if we've asked enough questions and should just classify.
        """
        return self.clarification_count >= max_attempts

    def reset_clarification_state(self) -> None:
        """Reset clarification state (e.g., when user corrects or starts new issue)."""
        self.clarification_count = 0
        self.asked_questions = []
        self.clarified_aspects = set()
        self.cumulative_issue = None
        self.missing_slots = []
        self.clarification_options = {}
        self.classification_miss_count = 0
        self.we_dont_understand_offered = False
        self.pending_location = None
    
    # NEW: Behavior Contract Methods
    
    def detect_domain_change(self, new_domain: Optional[str]) -> bool:
        """
        Detect if user switched topics/domains.
        Returns True if domain changed (topic switch).
        """
        if not new_domain or not self.last_detected_domain:
            return False
        
        if new_domain != self.last_detected_domain:
            self.domain_history.append(new_domain)
            return True
        return False
    
    def update_domain(self, domain: Optional[str]) -> None:
        """Update the current domain being discussed."""
        if domain and domain != self.last_detected_domain:
            if self.last_detected_domain:
                self.domain_history.append(self.last_detected_domain)
            self.last_detected_domain = domain
    
    def store_candidates(self, candidates: List[Dict[str, Any]]) -> None:
        """Store top-N candidates from classification."""
        self.candidate_call_types = candidates[:10]  # Keep top 10
    
    def get_top_candidate(self) -> Optional[Dict[str, Any]]:
        """Get the top candidate from stored candidates."""
        if self.candidate_call_types:
            return self.candidate_call_types[0]
        return None
    
    def update_confidence_band(self, confidence: float) -> None:
        """
        Update confidence band based on numeric confidence.
        Low: < 0.4
        Medium: 0.4 - 0.7
        High: >= 0.7
        """
        if confidence < 0.4:
            self.confidence_band = "low"
        elif confidence < 0.7:
            self.confidence_band = "medium"
        else:
            self.confidence_band = "high"
        
        self.last_classification_confidence = confidence
    
    def collect_slot(self, slot_name: str, value: Any) -> None:
        """Collect a slot value from user response."""
        self.collected_slots[slot_name] = value
    
    def has_all_required_slots(self) -> bool:
        """Check if all required slots have been collected."""
        if not self.required_slots:
            return True
        return all(slot in self.collected_slots for slot in self.required_slots.keys())
    
    def get_missing_slot(self) -> Optional[str]:
        """Get the next missing slot that needs to be collected."""
        for slot in self.required_slots.keys():
            if slot not in self.collected_slots:
                return slot
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict representation."""
        if self.location is None:
            location_value: Any = None
        elif hasattr(self.location, "__dict__"):
            location_value = self.location.__dict__
        else:
            location_value = self.location

        return {
            "messages": self.messages,
            "issue_summary": self.issue_summary,
            "call_type_code": self.call_type_code,
            "location": location_value,
            "confirmed": self.confirmed,
            "missing_slots": list(self.missing_slots) if self.missing_slots else [],
            "clarification_count": self.clarification_count,
        }
