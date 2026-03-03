"""
Middleware and exception handlers for the CSD Chatbot API.

This module is the single place where FastAPI middleware is configured.
Later phases of the refactor will extend this with security and
structured error handling as described in CURSOR_REFACTORING_INSTRUCTIONS.
"""

from typing import Iterable
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import settings
from src.models.schemas import ErrorResponse, ErrorCode


logger = logging.getLogger(__name__)

MAX_REQUEST_SIZE = 1_000_000  # 1MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE:
            return JSONResponse(
                status_code=413,
                content={"error": "Request too large"},
            )
        return await call_next(request)


async def global_exception_handler(request: Request, exc: Exception):
    import uuid

    request_id = str(uuid.uuid4())[:8]
    logger.error("[%s] Unhandled exception: %s", request_id, exc, exc_info=True)

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred",
            request_id=request_id,
        ).dict(),
    )


def _compute_allowed_origins(additional_origins: Iterable[str] | None = None) -> list[str]:
    """
    Compute allowed CORS origins following CURSOR_REFACTORING_INSTRUCTIONS.
    """
    env_value = os.getenv("ALLOWED_ORIGINS", "").strip()
    if env_value:
        base_origins = [o.strip() for o in env_value.split(",") if o.strip()]
    else:
        base_origins = []

    if not base_origins:
        base_origins = ["http://localhost:3000"]

    if additional_origins:
        for origin in additional_origins:
            if origin and origin not in base_origins:
                base_origins.append(origin)

    return base_origins


def setup_middleware(app: FastAPI, additional_origins: Iterable[str] | None = None) -> None:
    """
    Configure middleware for the FastAPI application.

    - Restricts CORS origins based on ALLOWED_ORIGINS env (no "*" default).
    - Adds request size limiting middleware.
    - Registers a global exception handler returning structured ErrorResponse.
    """
    allowed_origins = _compute_allowed_origins(additional_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_exception_handler(Exception, global_exception_handler)


__all__ = ["setup_middleware", "RequestSizeLimitMiddleware", "global_exception_handler"]

