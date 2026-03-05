"""
Rate limiting middleware for API protection
"""
import time
from typing import Dict
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, list] = defaultdict(list)
        self._cleanup_interval = 60  # Clean up old entries every 60 seconds
        self._last_cleanup = time.time()
    
    def _cleanup_old_entries(self):
        """Remove entries older than 1 minute"""
        current_time = time.time()
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
        
        cutoff_time = current_time - 60
        for key in list(self.requests.keys()):
            self.requests[key] = [
                req_time for req_time in self.requests[key]
                if req_time > cutoff_time
            ]
            if not self.requests[key]:
                del self.requests[key]
        
        self._last_cleanup = current_time
    
    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """
        Check if request is allowed
        Returns: (is_allowed, remaining_requests)
        """
        self._cleanup_old_entries()
        
        current_time = time.time()
        cutoff_time = current_time - 60
        
        # Remove old requests
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier]
            if req_time > cutoff_time
        ]
        
        # Check if limit exceeded
        if len(self.requests[identifier]) >= self.requests_per_minute:
            return False, 0
        
        # Add current request
        self.requests[identifier].append(current_time)
        
        remaining = self.requests_per_minute - len(self.requests[identifier])
        return True, remaining


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting"""
    
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rate_limiter = RateLimiter(requests_per_minute)
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/favicon.ico", "/"]:
            return await call_next(request)
        
        # Get client identifier (IP address or API key)
        client_id = request.client.host if request.client else "unknown"
        
        # Check for API key in header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            # Use API key as identifier for better tracking
            client_id = f"api_key:{api_key[:8]}"
        
        # Check rate limit
        allowed, remaining = self.rate_limiter.is_allowed(client_id)
        
        if not allowed:
            logger.warning(f"Rate limit exceeded for {client_id}")
            return Response(
                content='{"error": "Rate limit exceeded. Please try again later."}',
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(self.rate_limiter.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60"
                },
                media_type="application/json"
            )
        
        # Add rate limit headers
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response
