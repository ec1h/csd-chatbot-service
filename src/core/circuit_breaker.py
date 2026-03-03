import time
from typing import Callable, Any
from functools import wraps
import logging


logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exceptions: tuple = (Exception,),
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half-open"
                else:
                    raise CircuitBreakerOpen("Service temporarily unavailable")

            try:
                result = func(*args, **kwargs)
                if self.state == "half-open":
                    self.state = "closed"
                    self.failures = 0
                return result
            except self.expected_exceptions:
                self.failures += 1
                self.last_failure_time = time.time()
                if self.failures >= self.failure_threshold:
                    self.state = "open"
                    logger.error(
                        "Circuit breaker opened after %s failures", self.failures
                    )
                raise

        return wrapper


class CircuitBreakerOpen(Exception):
    pass


__all__ = ["CircuitBreaker", "CircuitBreakerOpen"]

