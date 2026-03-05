"""
Error handling and resilience utilities
"""
import logging
import time
from functools import wraps
from typing import Callable, Any, Optional, TypeVar, ParamSpec
from fastapi import HTTPException

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class RetryableError(Exception):
    """Error that can be retried"""
    pass


class NonRetryableError(Exception):
    """Error that should not be retried"""
    pass


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Decorator for retrying functions with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exceptions that can be retried
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * exponential_base, max_delay)
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                        raise
                except Exception as e:
                    # Non-retryable exception
                    logger.error(f"{func.__name__} failed with non-retryable error: {e}")
                    raise
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed unexpectedly")
        
        return wrapper
    return decorator


def safe_execute(
    func: Callable[P, T],
    default: Optional[T] = None,
    error_message: str = "Operation failed",
    log_error: bool = True
) -> Optional[T]:
    """
    Safely execute a function with error handling
    
    Args:
        func: Function to execute
        default: Default value to return on error
        error_message: Error message to log
        log_error: Whether to log errors
    
    Returns:
        Function result or default value
    """
    try:
        return func()
    except Exception as e:
        if log_error:
            logger.error(f"{error_message}: {e}", exc_info=True)
        return default


def handle_llm_error(error: Exception, context: str = "") -> str:
    """
    Handle LLM-related errors gracefully
    
    Returns:
        User-friendly error message
    """
    error_str = str(error).lower()
    
    if "rate limit" in error_str or "quota" in error_str:
        logger.error(f"LLM rate limit exceeded: {context}")
        return "I'm experiencing high demand right now. Please try again in a moment."
    
    if "timeout" in error_str or "timed out" in error_str:
        logger.error(f"LLM timeout: {context}")
        return "The request is taking longer than expected. Please try again."
    
    if "authentication" in error_str or "unauthorized" in error_str:
        logger.error(f"LLM authentication error: {context}")
        return "There's a configuration issue. Please contact support."
    
    logger.error(f"LLM error: {error} - {context}")
    return "I'm having trouble processing that. Could you please rephrase your question?"


def validate_session_state(state: dict) -> bool:
    """
    Validate conversation state structure
    
    Returns:
        True if valid, False otherwise
    """
    required_keys = ["conversation_phase", "problem_understanding", "confidence_factors"]
    
    for key in required_keys:
        if key not in state:
            logger.warning(f"Missing required state key: {key}")
            return False
    
    return True
