"""
Issue Summary Builder - Deterministic Summary Construction
==========================================================
This module constructs issue summaries according to the Issue Summary Contract:
- Short
- Deterministic
- Derived ONLY from final call type + structured details
- MUST NOT contain: user confirmations, locations, polite phrases, raw user utterances
"""

from src.conversation.case_memory import CaseMemory
from typing import Optional


def build_issue_summary(memory: CaseMemory) -> str:
    """
    Build a deterministic issue summary from memory.
    
    Contract:
    - Short
    - Deterministic
    - Derived ONLY from final call type + structured details
    - MUST NOT contain: user confirmations, locations, polite phrases, raw user utterances
    
    Args:
        memory: CaseMemory with call_type_code and issue_summary
        
    Returns:
        A clean, short issue summary suitable for submission
    """
    # If we have a call type code, use the canonical issue summary
    if memory.call_type_code and memory.issue_summary:
        # Return the clean issue summary (already sanitized by classifier)
        return memory.issue_summary
    
    # Fallback: if we have issue_summary but no code, use it
    if memory.issue_summary:
        return memory.issue_summary
    
    # No issue identified yet
    return "Issue"


def build_submission_summary(memory: CaseMemory) -> str:
    """
    Build the final issue summary for ticket submission.
    
    This is the summary that goes into the ticket system.
    It must be clean, deterministic, and contain only structured information.
    
    Contract:
    - Short
    - Deterministic
    - Derived ONLY from final call type + structured details
    - MUST NOT contain: user confirmations, locations, polite phrases, raw user utterances
    
    Args:
        memory: CaseMemory with confirmed issue
        
    Returns:
        A clean summary for ticket submission
    """
    # Use the canonical issue summary from the call type
    summary = build_issue_summary(memory)
    
    # Ensure it's short (max 100 chars for safety)
    if len(summary) > 100:
        # Truncate at word boundary
        truncated = summary[:97] + "..."
        return truncated
    
    return summary
