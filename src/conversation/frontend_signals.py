"""
Frontend Signals - Strict State-Based Flags
===========================================
This generates frontend flags based ONLY on state.
Rules:
- Flags depend only on state
- Never on confidence
"""

from src.conversation.conversation_state import ConversationState
from src.conversation.case_memory import CaseMemory
from typing import Dict, Optional, Any


def get_frontend_flags(state: ConversationState, memory: Optional[CaseMemory] = None) -> Dict[str, Any]:
    """
    Get frontend flags based on conversation state.
    
    Rules:
    - Flags depend only on state
    - Never on confidence
    """
    flags = {
        "needs_location": state == ConversationState.NEEDS_LOCATION,
        "conversation_done": state == ConversationState.SUBMITTED,
        "chat_locked": state == ConversationState.SUBMITTED
    }
    
    # NEW: Include selected call type in response
    if memory and memory.selected_call_type:
        flags["selected_calltype"] = memory.selected_call_type
    
    return flags
