"""
FastAPI route handlers for the CSD Chatbot.

This module contains all API endpoints extracted from app.py.
All route handlers maintain identical behavior and response shapes.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from psycopg2.extras import Json

from src.models.schemas import (
    ChatRequest,
    ChatHistoryResponse,
    ChatHistoryMessage,
    ChatMessagesRequest,
    MessagePayload,
    PaginationInfo,
    UpdateTitleRequest,
    UpdateTitleResponse,
)
from src.api.dependencies import verify_api_key_header
from src.core.session_manager import load_session, save_message, get_messages
from src.database.connection import pg_fetchone, pg_execute
from src.security.input_sanitizer import sanitize_input
from src.conversation.conversation_state import ConversationState, ConversationPhase
from src.conversation.case_memory import CaseMemory
from src.core.orchestrator import process_user_message
# Import helper functions from domain logic
from src.core.domain_logic import (
    set_location_data,
    get_working_memory,
    generate_suggested_answers,
)

router = APIRouter()


# Helper functions that are endpoint-specific or need to stay with endpoints for now
def _row_to_session(row: dict) -> Dict[str, Any]:
    """Convert database row to session dict."""
    messages = row.get("messages") or []
    pending = row.get("pending") or {}
    state_str = row.get("state") or ConversationState.OPEN.value
    try:
        ConversationState(state_str)  # Validate
    except ValueError:
        state_str = ConversationState.OPEN.value

    return {
        "_id": row["session_id"],
        "chat_id": row["chat_id"],
        "session_id": row["session_id"].split(":", 1)[1] if ":" in row["session_id"] else "",
        "title": row.get("title") or "New conversation",
        "messages": messages,
        "state": state_str,
        "pending": pending,
    }


def _session_to_memory_and_state(session: Dict[str, Any]) -> tuple[CaseMemory, ConversationState]:
    """Convert old session format to new CaseMemory and ConversationState."""
    pending = session.get("pending", {})
    working_memory = pending.get("workingMemory", {})
    messages = session.get("messages", [])

    user_messages = [msg.get("content", "") for msg in messages if msg.get("role") == "user"]

    memory = CaseMemory(
        messages=user_messages,
        issue_summary=working_memory.get("callType") or working_memory.get("call_type"),
        call_type_code=working_memory.get("callTypeCode") or working_memory.get("call_type_code"),
        location=working_memory.get("location"),
        confirmed=working_memory.get("callTypeLocked", False)
        and not working_memory.get("awaitingConfirmation", False),
        missing_slots=working_memory.get("missingSlots", []) or [],
        clarification_options=working_memory.get("clarificationOptions", {}) or {},
        last_intent_summary=working_memory.get("lastIntentSummary"),
        in_correction_mode=working_memory.get("inCorrectionMode", False),
        clarification_count=working_memory.get("clarificationCount", 0),  # FIX: Load clarification counter
        classification_miss_count=working_memory.get("classificationMissCount", 0),  # FIX: Load miss counter
    )

    # Determine current state from working memory
    location_required = working_memory.get("locationRequired", False)
    awaiting_confirmation = working_memory.get("awaitingConfirmation", False)
    awaiting_clarification = working_memory.get("awaitingClarification", False)

    if memory.confirmed:
        state = ConversationState.SUBMITTED
    elif awaiting_confirmation:
        state = ConversationState.CONFIRMING
    elif awaiting_clarification:
        state = ConversationState.AWAITING_CLARIFICATION
    elif location_required and memory.call_type_code:
        state = ConversationState.NEEDS_LOCATION
    elif memory.issue_summary or memory.call_type_code:
        state = ConversationState.ISSUE_BUILDING
    else:
        state = ConversationState.OPEN

    return memory, state


def _save_memory_and_state_to_session(
    session: Dict[str, Any], memory: CaseMemory, state: ConversationState
) -> None:
    """Save CaseMemory and ConversationState back to session format."""
    pending = session.get("pending", {})
    working_memory = pending.get("workingMemory", {})

    working_memory["callType"] = memory.issue_summary
    working_memory["call_type"] = memory.issue_summary
    working_memory["callTypeCode"] = memory.call_type_code
    working_memory["call_type_code"] = memory.call_type_code
    working_memory["location"] = memory.location
    working_memory["issueSummary"] = memory.issue_summary
    working_memory["callTypeLocked"] = memory.confirmed
    working_memory["awaitingConfirmation"] = (state == ConversationState.CONFIRMING)
    working_memory["locationRequired"] = (state == ConversationState.NEEDS_LOCATION)
    working_memory["awaitingClarification"] = (state == ConversationState.AWAITING_CLARIFICATION)
    working_memory["missingSlots"] = memory.missing_slots
    working_memory["clarificationOptions"] = memory.clarification_options
    working_memory["lastIntentSummary"] = memory.last_intent_summary
    working_memory["inCorrectionMode"] = memory.in_correction_mode
    working_memory["clarificationCount"] = memory.clarification_count  # FIX: Save clarification counter
    working_memory["classificationMissCount"] = memory.classification_miss_count  # FIX: Save miss counter

    # Map new states to old conversation phases
    state_to_phase = {
        ConversationState.OPEN: ConversationPhase.OPEN_INTAKE,
        ConversationState.ISSUE_BUILDING: ConversationPhase.PROBLEM_NARROWING,
        ConversationState.AWAITING_CLARIFICATION: ConversationPhase.PROBLEM_NARROWING,
        ConversationState.NEEDS_LOCATION: ConversationPhase.DETAIL_COLLECTION,
        ConversationState.CONFIRMING: ConversationPhase.CONFIRMATION,
        ConversationState.SUBMITTED: ConversationPhase.LOCKED_FOR_SUBMISSION,
    }
    working_memory["conversation_phase"] = state_to_phase.get(state, ConversationPhase.OPEN_INTAKE)

    pending["workingMemory"] = working_memory
    session["pending"] = pending

    pg_execute(
        "UPDATE ec1_chat_history SET pending = %s, updated_at = NOW() WHERE session_id = %s",
        (Json(pending), session["_id"]),
    )


@router.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@router.get("/favicon.ico")
def favicon():
    """Favicon endpoint."""
    return {}


@router.get("/")
def root():
    """Root endpoint."""
    return {"message": "Hello from Lambda!"}


@router.post("/chat")
def chat(body: ChatRequest, api_key=Depends(verify_api_key_header)):
    """
    Main chat endpoint - processes user messages through the orchestrator.
    
    Maintains identical behavior and response shape to the original implementation.
    """
    created = datetime.now(timezone.utc)
    # Sanitize user input as early as possible
    sanitized_message = sanitize_input(body.message)
    if sanitized_message != body.message:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("Input was sanitized for chat request")

    session = load_session(body.chat_id, body.session_id)
    save_message(session, "user", sanitized_message)

    # Convert session to new format
    memory, current_state = _session_to_memory_and_state(session)

    # Handle external location data from map picker
    external_location = None
    if body.location:
        location_dict = body.location
        external_location = location_dict.get("address", "") or f"{location_dict.get('latitude', '')}, {location_dict.get('longitude', '')}"
        set_location_data(session, body.location)
        # Reload session to get updated pending data
        session = load_session(body.chat_id, body.session_id)
        memory, current_state = _session_to_memory_and_state(session)

    # Process through orchestrator (THE ONLY PLACE WHERE LAYERS CONNECT)
    result = process_user_message(
        user_text=sanitized_message,
        current_state=current_state,
        memory=memory,
        external_location=external_location,
    )

    # Save back to session
    _save_memory_and_state_to_session(session, result["memory"], result["state"])

    # Extract response
    assistant_message = result["response"]
    frontend_flags = result["frontend_flags"]
    _is_submitted = (result["state"] == ConversationState.SUBMITTED)
    _is_confirming = (result["state"] == ConversationState.CONFIRMING)

    _ct_code = str(result["memory"].call_type_code) if result["memory"].call_type_code else None
    _ct_desc = result["memory"].issue_summary if result["memory"].issue_summary else None
    _ct_conf = getattr(result["memory"], "last_classification_confidence", None)

    # Minimal message block — response text + two flags only
    message_block = {
        "response": assistant_message,
        "needs_location": frontend_flags["needs_location"],
        "chat_locked": frontend_flags.get("chat_locked", False),
    }

    # Generate suggested answers
    current_state_dict = get_working_memory(session)
    last_user_msg = result["memory"].messages[-1] if result["memory"].messages else None
    suggested_answers = generate_suggested_answers(
        current_state_dict,
        last_user_message=last_user_msg,
        bot_response=assistant_message,
        current_state=result["state"],
        needs_location=frontend_flags["needs_location"],
    )

    msg_id = save_message(session, "assistant", message_block)

    return {
        "session_id": session["_id"],
        "chat_message_id": msg_id,
        "created": created.isoformat(),
        "message": message_block,
        "classification": {
            "call_type_code": _ct_code,
            "call_type_description": _ct_desc,
            "confidence": _ct_conf,
        } if _ct_code else None,
        "state": result["state"].value if hasattr(result["state"], "value") else str(result["state"]),
        "suggested_answers": suggested_answers,
        "frontend_flags": {
            "needs_location": frontend_flags["needs_location"],
            "show_map": frontend_flags["needs_location"],
            "conversation_done": _is_submitted,
            "chat_locked": frontend_flags.get("chat_locked", False),
            "show_confirmation": _is_confirming,
        },
        "chat_message_type": "Assistant",
        "awaitingConfirmation": _is_confirming,
    }


@router.post("/chatStream")
def chat_stream(body: ChatRequest, api_key=Depends(verify_api_key_header)):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).

    Uses the same orchestrator pattern as /chat endpoint.
    """
    created = datetime.now(timezone.utc)
    sanitized_message = sanitize_input(body.message)
    if sanitized_message != body.message:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("Input was sanitized for streaming chat request")

    session = load_session(body.chat_id, body.session_id)
    save_message(session, "user", sanitized_message)

    # Convert session to new format
    memory, current_state = _session_to_memory_and_state(session)

    # Handle external location data from map picker
    external_location = None
    if body.location:
        location_dict = body.location
        external_location = location_dict.get("address", "") or f"{location_dict.get('latitude', '')}, {location_dict.get('longitude', '')}"
        set_location_data(session, body.location)
        session = load_session(body.chat_id, body.session_id)
        memory, current_state = _session_to_memory_and_state(session)

    # Process through orchestrator (same as /chat endpoint)
    result = process_user_message(
        user_text=sanitized_message,
        current_state=current_state,
        memory=memory,
        external_location=external_location,
    )

    # Save back to session
    _save_memory_and_state_to_session(session, result["memory"], result["state"])

    # Extract response
    assistant_message = result["response"]
    frontend_flags = result["frontend_flags"]

    _sct_code = str(result["memory"].call_type_code) if result["memory"].call_type_code else None
    _sct_desc = result["memory"].issue_summary if result["memory"].issue_summary else None
    _sct_conf = getattr(result["memory"], "last_classification_confidence", None)
    _s_submitted = (result["state"] == ConversationState.SUBMITTED)
    _s_confirming = (result["state"] == ConversationState.CONFIRMING)

    # Minimal message block
    stream_message_block = {
        "response": assistant_message,
        "needs_location": frontend_flags["needs_location"],
        "chat_locked": frontend_flags.get("chat_locked", False),
    }

    current_state_dict = get_working_memory(session)
    last_user_msg = result["memory"].messages[-1] if result["memory"].messages else None
    sq = generate_suggested_answers(
        current_state_dict,
        last_user_message=last_user_msg,
        bot_response=assistant_message,
        current_state=result["state"],
        needs_location=frontend_flags["needs_location"],
    )

    stream_text = assistant_message
    msg_id = save_message(session, "assistant", "")

    base_payload = {
        "session_id": session["_id"],
        "chat_message_id": msg_id,
        "created": created.isoformat(),
        "message": stream_message_block,
        "classification": {
            "call_type_code": _sct_code,
            "call_type_description": _sct_desc,
            "confidence": _sct_conf,
        } if _sct_code else None,
        "state": result["state"].value if hasattr(result["state"], "value") else str(result["state"]),
        "suggested_answers": sq,
        "frontend_flags": {
            "needs_location": frontend_flags["needs_location"],
            "show_map": frontend_flags["needs_location"],
            "conversation_done": _s_submitted,
            "chat_locked": frontend_flags.get("chat_locked", False),
            "show_confirmation": _s_confirming,
        },
        "chat_message_type": "Assistant",
        "awaitingConfirmation": _s_confirming,
    }

    meta_payload = jsonable_encoder(base_payload)

    def _stream():
        yield f"data: {json.dumps({'type':'meta','payload': meta_payload})}\n\n"
        for tok in stream_text.split(" "):
            token = tok + " "
            yield f"data: {json.dumps({'type':'token','payload': token})}\n\n"
            time.sleep(0.01)
        msgs = get_messages(session["_id"])
        if msgs and msgs[-1]["role"] == "assistant" and str(msgs[-1]["ts"]) == msg_id:
            msgs[-1]["content"] = stream_message_block
            pg_execute(
                "UPDATE ec1_chat_history SET messages = %s, updated_at = NOW() WHERE session_id = %s",
                (Json(msgs), session["_id"]),
            )
        done_payload = jsonable_encoder(base_payload)
        yield f"data: {json.dumps({'type':'done','payload': done_payload})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/getChatMessages", response_model=ChatHistoryResponse)
def chat_messages_post(
    body: ChatMessagesRequest,
    api_key=Depends(verify_api_key_header),
    page: int = Query(1, ge=1),
    size: int = Query(15, ge=1, le=100),
):
    """Get chat messages for a session with pagination."""
    if body.SessionId:
        sid = f"{body.ChatId}:{body.SessionId}"
        doc = pg_fetchone("SELECT * FROM ec1_chat_history WHERE session_id = %s", (sid,))
        if not doc:
            raise HTTPException(status_code=404, detail="Chat session not found")
    else:
        doc = pg_fetchone(
            "SELECT * FROM ec1_chat_history WHERE chat_id = %s ORDER BY updated_at DESC LIMIT 1",
            (body.ChatId,),
        )
        if not doc:
            raise HTTPException(status_code=404, detail="No sessions found for ChatId")

    session = _row_to_session(doc)
    all_msgs = session.get("messages", []) or []
    total = len(all_msgs)

    start = (page - 1) * size
    end = start + size
    page_msgs = all_msgs[start:end]

    items: List[ChatHistoryMessage] = []
    for m in page_msgs:
        ts = m.get("ts", time.time())
        content = m.get("content", "")
        items.append(
            ChatHistoryMessage(
                chat_message_id=str(ts),
                created=datetime.fromtimestamp(ts, tz=timezone.utc),
                message=content,
                role="user" if m.get("role") == "user" else "assistant",
            )
        )

    return ChatHistoryResponse(
        session_id=str(session["_id"]),
        messages=items,
        pagination=PaginationInfo(
            total=total,
            page=page,
            size=size,
            pages=(total + size - 1) // size,
        ),
    )


@router.post("/getChatHistory", response_model=ChatHistoryResponse)
def chat_history_post(
    body: ChatMessagesRequest,
    api_key=Depends(verify_api_key_header),
    page: int = Query(1, ge=1),
    size: int = Query(15, ge=1, le=100),
):
    """Get chat history for a chat ID with pagination."""
    if not body.ChatId:
        raise HTTPException(status_code=400, detail="ChatId is required")

    doc = pg_fetchone(
        "SELECT * FROM ec1_chat_history WHERE session_id LIKE %s ORDER BY updated_at DESC LIMIT 1",
        (f"{body.ChatId}:%",),
    )
    if not doc:
        raise HTTPException(status_code=404, detail="No sessions found for ChatId")

    session = _row_to_session(doc)
    all_msgs = session.get("messages", []) or []
    total = len(all_msgs)

    start = (page - 1) * size
    end = start + size
    page_msgs = all_msgs[start:end]

    items: List[ChatHistoryMessage] = []
    for m in page_msgs:
        ts = m.get("ts", time.time())
        content = m.get("content", "")
        role = "user" if m.get("role") == "user" else "assistant"

        if role == "assistant" and isinstance(content, dict) and "response" in content and "list" in content:
            msg_value = content
        else:
            msg_value = str(content)

        items.append(
            ChatHistoryMessage(
                chat_message_id=str(ts),
                created=datetime.fromtimestamp(ts, tz=timezone.utc),
                message=msg_value,
                role=role,
            )
        )

    return ChatHistoryResponse(
        session_id=str(session["_id"]),
        messages=items,
        pagination=PaginationInfo(
            total=total,
            page=page,
            size=size,
            pages=(total + size - 1) // size,
        ),
    )


@router.post("/updateChatTitle", response_model=UpdateTitleResponse)
def update_title(body: UpdateTitleRequest, api_key=Depends(verify_api_key_header)):
    """Update the title of a chat session."""
    session = load_session(body.chat_id, body.session_id)
    pg_execute(
        "UPDATE ec1_chat_history SET title = %s, updated_at = NOW() WHERE session_id = %s",
        (body.title, session["_id"]),
    )
    return UpdateTitleResponse(session_id=session["_id"], title=body.title, message="Title updated.")


__all__ = ["router"]
