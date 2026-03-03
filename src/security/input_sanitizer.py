"""
Input sanitization and validation utilities
"""
import re
import html
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """
    Sanitize user input to prevent injection attacks
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length
    
    Returns:
        Sanitized text
    """
    if not isinstance(text, str):
        return ""
    
    # Trim whitespace
    text = text.strip()
    
    # Check length
    if len(text) > max_length:
        logger.warning(f"Input truncated from {len(text)} to {max_length} characters")
        text = text[:max_length]
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # Escape HTML to prevent XSS
    text = html.escape(text)
    
    # Remove excessive whitespace (more than 2 consecutive spaces)
    text = re.sub(r' {3,}', ' ', text)
    
    # Remove excessive newlines (more than 2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text


def validate_message_length(text: str, max_length: int = 2000) -> tuple[bool, Optional[str]]:
    """
    Validate message length
    
    Returns:
        (is_valid, error_message)
    """
    if not text or not text.strip():
        return False, "Message cannot be empty"
    
    if len(text) > max_length:
        return False, f"Message is too long. Maximum {max_length} characters allowed."
    
    return True, None


def contains_sql_injection(text: str) -> bool:
    """
    Basic SQL injection detection
    
    Note: This is a simple check. Parameterized queries should always be used.
    """
    sql_keywords = [
        r'\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b',
        r'--',  # SQL comment
        r'/\*',  # SQL comment
        r';\s*(DROP|DELETE|TRUNCATE)',  # Command chaining
        r'UNION\s+SELECT',
        r'OR\s+1\s*=\s*1',
        r'AND\s+1\s*=\s*1',
    ]
    
    text_upper = text.upper()
    for pattern in sql_keywords:
        if re.search(pattern, text_upper, re.IGNORECASE):
            logger.warning(f"Potential SQL injection detected: {pattern}")
            return True
    
    return False


def contains_xss_attempt(text: str) -> bool:
    """
    Basic XSS detection
    """
    xss_patterns = [
        r'<script[^>]*>',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe',
        r'<object',
        r'<embed',
    ]
    
    for pattern in xss_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Potential XSS detected: {pattern}")
            return True
    
    return False
