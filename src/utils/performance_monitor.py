"""
Performance Monitoring and Optimization
========================================
Real-time performance tracking and optimization for classification.

Features:
- Request-level timing
- LRU cache for frequent queries
- Performance metrics and alerts
- Query result caching
"""

import logging
import time
import hashlib
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from collections import OrderedDict
from functools import wraps
from threading import Lock
import json

logger = logging.getLogger(__name__)


class LRUCache:
    """
    Thread-safe LRU (Least Recently Used) cache.
    
    Caches classification results for frequently asked queries.
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self.cache: OrderedDict[str, Dict] = OrderedDict()
        self.lock = Lock()
        
        # Stats
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def _make_key(self, user_text: str, context: Optional[Dict] = None) -> str:
        """Create cache key from user text and context"""
        # Normalize text
        text_normalized = user_text.lower().strip()
        
        # Include context in key if provided
        if context:
            context_str = json.dumps(context, sort_keys=True)
            key_input = f"{text_normalized}|{context_str}"
        else:
            key_input = text_normalized
        
        # Hash for consistent key
        return hashlib.md5(key_input.encode()).hexdigest()
    
    def get(self, user_text: str, context: Optional[Dict] = None) -> Optional[Dict]:
        """Get cached result"""
        key = self._make_key(user_text, context)
        
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None
            
            entry = self.cache[key]
            
            # Check if expired
            if datetime.now() - entry["timestamp"] > self.ttl:
                del self.cache[key]
                self.misses += 1
                return None
            
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            
            self.hits += 1
            return entry["result"]
    
    def set(self, user_text: str, result: Dict, context: Optional[Dict] = None):
        """Cache result"""
        key = self._make_key(user_text, context)
        
        with self.lock:
            # Add to cache
            self.cache[key] = {
                "result": result,
                "timestamp": datetime.now()
            }
            
            # Move to end
            self.cache.move_to_end(key)
            
            # Evict oldest if over size
            if len(self.cache) > self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                self.evictions += 1
    
    def clear(self):
        """Clear cache"""
        with self.lock:
            self.cache.clear()
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "evictions": self.evictions
            }


class PerformanceMonitor:
    """
    Performance monitoring for classification operations.
    
    Tracks:
    - Request latency (p50, p95, p99)
    - Throughput (requests/second)
    - Cache effectiveness
    - Error rates
    """
    
    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        
        # Timing data
        self.latencies: List[float] = []
        self.lock = Lock()
        
        # Counters
        self.total_requests = 0
        self.errors = 0
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Request tracking
        self.request_timestamps: List[datetime] = []
        
        # Component timings
        self.component_times = {
            "intent_detection": [],
            "candidate_selection": [],
            "semantic_ranking": [],
            "final_scoring": []
        }
    
    def record_request(
        self,
        latency_ms: float,
        cached: bool = False,
        error: bool = False,
        component_times: Optional[Dict[str, float]] = None
    ):
        """Record a classification request"""
        with self.lock:
            self.total_requests += 1
            self.request_timestamps.append(datetime.now())
            
            if error:
                self.errors += 1
            
            if cached:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            
            # Record latency
            self.latencies.append(latency_ms)
            
            # Keep only recent data (sliding window)
            if len(self.latencies) > self.window_size:
                self.latencies.pop(0)
            
            # Record component times
            if component_times:
                for component, time_ms in component_times.items():
                    if component in self.component_times:
                        self.component_times[component].append(time_ms)
                        if len(self.component_times[component]) > self.window_size:
                            self.component_times[component].pop(0)
            
            # Clean old timestamps (keep last hour)
            cutoff = datetime.now() - timedelta(hours=1)
            self.request_timestamps = [
                ts for ts in self.request_timestamps if ts > cutoff
            ]
    
    def get_percentile(self, percentile: float) -> float:
        """Get latency percentile"""
        with self.lock:
            if not self.latencies:
                return 0.0
            
            sorted_latencies = sorted(self.latencies)
            idx = int(len(sorted_latencies) * percentile)
            return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    def get_throughput(self) -> float:
        """Get requests per second (last hour)"""
        with self.lock:
            if not self.request_timestamps:
                return 0.0
            
            # Count requests in last minute for more accurate rate
            cutoff = datetime.now() - timedelta(minutes=1)
            recent_count = sum(1 for ts in self.request_timestamps if ts > cutoff)
            
            return recent_count / 60.0  # Requests per second
    
    def get_statistics(self) -> Dict:
        """Get comprehensive performance statistics"""
        stats = {
            "total_requests": self.total_requests,
            "errors": self.errors,
            "error_rate": self.errors / max(self.total_requests, 1),
            "cache_hit_rate": self.cache_hits / max(self.cache_hits + self.cache_misses, 1),
            "throughput_rps": self.get_throughput(),
            "latency": {
                "p50_ms": self.get_percentile(0.50),
                "p95_ms": self.get_percentile(0.95),
                "p99_ms": self.get_percentile(0.99),
                "avg_ms": sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
            },
            "component_times": {}
        }
        
        # Add component timing breakdown
        for component, times in self.component_times.items():
            if times:
                stats["component_times"][component] = {
                    "avg_ms": sum(times) / len(times),
                    "p95_ms": sorted(times)[int(len(times) * 0.95)] if len(times) > 0 else 0.0
                }
        
        return stats
    
    def check_health(self) -> Dict[str, Any]:
        """Check system health and return status"""
        stats = self.get_statistics()
        
        # Health criteria
        health = {
            "status": "healthy",
            "issues": []
        }
        
        # Check latency
        if stats["latency"]["p95_ms"] > 1000:  # Over 1 second
            health["status"] = "degraded"
            health["issues"].append("High latency detected (p95 > 1s)")
        
        # Check error rate
        if stats["error_rate"] > 0.05:  # Over 5% errors
            health["status"] = "unhealthy"
            health["issues"].append(f"High error rate: {stats['error_rate']:.2%}")
        
        # Check cache effectiveness
        if stats["cache_hit_rate"] < 0.2 and self.total_requests > 100:
            health["issues"].append("Low cache hit rate (< 20%)")
        
        return {
            **health,
            "stats": stats
        }


def timed(component_name: str):
    """Decorator to time function execution"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.time() - start) * 1000
                logger.debug(f"{component_name} took {elapsed_ms:.2f}ms")
        return wrapper
    return decorator


class CachedClassifier:
    """
    Wrapper that adds caching to any classifier.
    
    Caches results based on user text to avoid redundant computation.
    """
    
    def __init__(
        self,
        classifier: Any,
        cache_size: int = 1000,
        cache_ttl_seconds: int = 3600,
        enable_monitoring: bool = True
    ):
        self.classifier = classifier
        self.cache = LRUCache(max_size=cache_size, ttl_seconds=cache_ttl_seconds)
        self.monitor = PerformanceMonitor() if enable_monitoring else None
    
    def classify(
        self,
        user_text: str,
        context: Optional[Dict] = None,
        **kwargs
    ) -> Dict:
        """Classify with caching"""
        start_time = time.time()
        component_times = {}
        
        # Check cache
        cache_context = {
            "domain": context.get("domain") if context else None,
            "category": context.get("category") if context else None
        }
        
        cached_result = self.cache.get(user_text, cache_context)
        
        if cached_result is not None:
            # Cache hit
            elapsed_ms = (time.time() - start_time) * 1000
            
            if self.monitor:
                self.monitor.record_request(
                    latency_ms=elapsed_ms,
                    cached=True,
                    error=False
                )
            
            logger.debug(f"Cache hit for query: {user_text[:50]}...")
            return cached_result
        
        # Cache miss - perform classification
        try:
            # Time each component
            intent_start = time.time()
            result = self.classifier.classify(user_text, **kwargs)
            component_times["total"] = (time.time() - intent_start) * 1000
            
            # Cache result
            self.cache.set(user_text, result, cache_context)
            
            # Record metrics
            elapsed_ms = (time.time() - start_time) * 1000
            
            if self.monitor:
                self.monitor.record_request(
                    latency_ms=elapsed_ms,
                    cached=False,
                    error=False,
                    component_times=component_times
                )
            
            return result
            
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            
            if self.monitor:
                self.monitor.record_request(
                    latency_ms=elapsed_ms,
                    cached=False,
                    error=True
                )
            
            logger.error(f"Classification error: {e}")
            raise
    
    def get_statistics(self) -> Dict:
        """Get performance and cache statistics"""
        stats = {
            "cache": self.cache.get_stats()
        }
        
        if self.monitor:
            stats["performance"] = self.monitor.get_statistics()
            stats["health"] = self.monitor.check_health()
        
        return stats
    
    def clear_cache(self):
        """Clear cache"""
        self.cache.clear()


# Global instances
_cached_classifier: Optional[CachedClassifier] = None
_performance_monitor: Optional[PerformanceMonitor] = None


def get_cached_classifier() -> Optional[CachedClassifier]:
    """Get global cached classifier"""
    return _cached_classifier


def set_cached_classifier(classifier: CachedClassifier):
    """Set global cached classifier"""
    global _cached_classifier
    _cached_classifier = classifier


def get_performance_monitor() -> Optional[PerformanceMonitor]:
    """Get global performance monitor"""
    return _performance_monitor


def initialize_performance_monitoring(classifier: Any) -> CachedClassifier:
    """Initialize performance monitoring with caching"""
    global _cached_classifier, _performance_monitor
    
    _cached_classifier = CachedClassifier(
        classifier=classifier,
        cache_size=1000,
        cache_ttl_seconds=3600,
        enable_monitoring=True
    )
    
    _performance_monitor = _cached_classifier.monitor
    
    logger.info("Performance monitoring initialized")
    return _cached_classifier


__all__ = [
    "LRUCache",
    "PerformanceMonitor",
    "CachedClassifier",
    "timed",
    "get_cached_classifier",
    "set_cached_classifier",
    "get_performance_monitor",
    "initialize_performance_monitoring"
]
