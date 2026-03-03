"""
Optimized Data Loader with Hot-Reload and Caching
=================================================
Fast, intelligent data loading with:
- Hot-reload detection (no restart needed for updates)
- Multi-level caching (memory + disk)
- Lazy loading for large datasets
- Performance monitoring
"""

import json
import glob
import logging
import pickle
from typing import Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime, timedelta
from threading import Lock
import time

logger = logging.getLogger(__name__)

# Global configuration
SCRIPT_DIR = Path(__file__).parent.parent.parent
REFINED_DATA_DIR = SCRIPT_DIR / "data" / "refined data" / "files"
CACHE_DIR = SCRIPT_DIR / ".cache" / "data_loader"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class CacheEntry:
    """Cache entry with metadata"""
    
    def __init__(self, data: any, file_hash: str, timestamp: datetime):
        self.data = data
        self.file_hash = file_hash
        self.timestamp = timestamp
        self.access_count = 0
        self.last_accessed = timestamp
    
    def access(self):
        """Record cache access"""
        self.access_count += 1
        self.last_accessed = datetime.now()
    
    def is_stale(self, current_hash: str) -> bool:
        """Check if cache is stale (file changed)"""
        return self.file_hash != current_hash


class HotReloadDataLoader:
    """
    Intelligent data loader with hot-reload capability.
    
    Features:
    - Automatic reload when JSON files change
    - Memory cache for fast access
    - Disk cache for faster startup
    - Background refresh (optional)
    """
    
    def __init__(
        self,
        data_dir: Path = REFINED_DATA_DIR,
        cache_dir: Path = CACHE_DIR,
        enable_disk_cache: bool = True,
        cache_ttl_seconds: int = 3600  # 1 hour
    ):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.enable_disk_cache = enable_disk_cache
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        
        # In-memory cache
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        
        # Performance tracking
        self.stats = {
            "loads": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "disk_cache_hits": 0,
            "reloads": 0,
            "total_load_time_ms": 0.0
        }
        
        # File watchers
        self._file_mtimes: Dict[Path, float] = {}
    
    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute hash of file for change detection"""
        if not file_path.exists():
            return ""
        
        # Use mtime + size for fast hash (good enough for change detection)
        stat = file_path.stat()
        return f"{stat.st_mtime}_{stat.st_size}"
    
    def _load_from_disk_cache(self, cache_key: str) -> Optional[CacheEntry]:
        """Load from disk cache if available"""
        if not self.enable_disk_cache:
            return None
        
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                entry = pickle.load(f)
            
            # Check if cache is too old
            if datetime.now() - entry.timestamp > self.cache_ttl:
                cache_file.unlink()
                return None
            
            self.stats["disk_cache_hits"] += 1
            return entry
            
        except Exception as e:
            logger.warning(f"Failed to load disk cache: {e}")
            return None
    
    def _save_to_disk_cache(self, cache_key: str, entry: CacheEntry):
        """Save to disk cache"""
        if not self.enable_disk_cache:
            return
        
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(entry, f)
        except Exception as e:
            logger.warning(f"Failed to save disk cache: {e}")
    
    def load_call_types(
        self,
        force_reload: bool = False,
        on_reload: Optional[Callable[[List[Dict]], None]] = None
    ) -> List[Dict]:
        """
        Load all call types with intelligent caching.
        
        Args:
            force_reload: Force reload even if cached
            on_reload: Callback function called when data is reloaded
            
        Returns:
            List of call type dictionaries
        """
        start_time = time.time()
        
        # Combined JSON file
        combined_file = self.data_dir / "all_call_types_combined.json"
        cache_key = "all_call_types"
        
        with self._lock:
            # Check memory cache first
            if not force_reload and cache_key in self._memory_cache:
                current_hash = self._compute_file_hash(combined_file)
                entry = self._memory_cache[cache_key]
                
                if not entry.is_stale(current_hash):
                    # Cache hit!
                    entry.access()
                    self.stats["cache_hits"] += 1
                    self.stats["loads"] += 1
                    return entry.data
                else:
                    # File changed - need reload
                    logger.info("Call types file changed, reloading...")
                    self.stats["reloads"] += 1
            
            # Cache miss - need to load
            self.stats["cache_misses"] += 1
            
            # Try disk cache
            if not force_reload:
                current_hash = self._compute_file_hash(combined_file)
                disk_entry = self._load_from_disk_cache(cache_key)
                
                if disk_entry and not disk_entry.is_stale(current_hash):
                    # Disk cache hit - load to memory
                    self._memory_cache[cache_key] = disk_entry
                    disk_entry.access()
                    self.stats["loads"] += 1
                    
                    elapsed = (time.time() - start_time) * 1000
                    self.stats["total_load_time_ms"] += elapsed
                    
                    logger.info(f"Loaded {len(disk_entry.data)} call types from disk cache in {elapsed:.2f}ms")
                    return disk_entry.data
            
            # Load from JSON
            call_types = self._load_from_json(combined_file)
            
            # Create cache entry
            current_hash = self._compute_file_hash(combined_file)
            entry = CacheEntry(call_types, current_hash, datetime.now())
            
            # Save to caches
            self._memory_cache[cache_key] = entry
            self._save_to_disk_cache(cache_key, entry)
            
            self.stats["loads"] += 1
            elapsed = (time.time() - start_time) * 1000
            self.stats["total_load_time_ms"] += elapsed
            
            logger.info(f"Loaded {len(call_types)} call types from JSON in {elapsed:.2f}ms")
            
            # Call reload callback if provided
            if on_reload:
                on_reload(call_types)
            
            return call_types
    
    def _load_from_json(self, combined_file: Path) -> List[Dict]:
        """Load call types from JSON files"""
        all_call_types = []
        
        # Try combined file first
        if combined_file.exists():
            try:
                with open(combined_file, 'r', encoding='utf-8') as f:
                    all_call_types = json.load(f)
                logger.info(f"Loaded {len(all_call_types)} call types from combined file")
                return all_call_types
            except Exception as e:
                logger.error(f"Failed to load combined file: {e}")
        
        # Fallback to individual files
        json_files = glob.glob(str(self.data_dir / "*.json"))
        for json_file in json_files:
            if "sample_data" in json_file or "combined" in json_file:
                continue
            
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_call_types.extend(data)
                logger.debug(f"Loaded {len(data)} call types from {Path(json_file).name}")
            except Exception as e:
                logger.error(f"Failed to load {json_file}: {e}")
        
        return all_call_types
    
    def check_for_updates(self) -> bool:
        """Check if data files have been updated"""
        combined_file = self.data_dir / "all_call_types_combined.json"
        current_hash = self._compute_file_hash(combined_file)
        
        cache_key = "all_call_types"
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key].is_stale(current_hash)
        
        return True  # No cache = needs load
    
    def reload_if_changed(
        self,
        on_reload: Optional[Callable[[List[Dict]], None]] = None
    ) -> Optional[List[Dict]]:
        """Reload data if files have changed"""
        if self.check_for_updates():
            logger.info("Data files changed, reloading...")
            return self.load_call_types(force_reload=True, on_reload=on_reload)
        return None
    
    def get_statistics(self) -> Dict:
        """Get loader statistics"""
        cache_hit_rate = 0.0
        if self.stats["loads"] > 0:
            cache_hit_rate = self.stats["cache_hits"] / self.stats["loads"]
        
        avg_load_time = 0.0
        if self.stats["loads"] > 0:
            avg_load_time = self.stats["total_load_time_ms"] / self.stats["loads"]
        
        return {
            **self.stats,
            "cache_hit_rate": cache_hit_rate,
            "avg_load_time_ms": avg_load_time,
            "memory_cache_size": len(self._memory_cache),
            "disk_cache_enabled": self.enable_disk_cache
        }
    
    def clear_cache(self, memory: bool = True, disk: bool = False):
        """Clear cache"""
        if memory:
            with self._lock:
                self._memory_cache.clear()
            logger.info("Cleared memory cache")
        
        if disk and self.enable_disk_cache:
            for cache_file in self.cache_dir.glob("*.pkl"):
                cache_file.unlink()
            logger.info("Cleared disk cache")
    
    def preload(self):
        """Preload data into cache (useful for startup)"""
        self.load_call_types()


# Global loader instance
_data_loader: Optional[HotReloadDataLoader] = None


def get_data_loader() -> HotReloadDataLoader:
    """Get global data loader instance"""
    global _data_loader
    
    if _data_loader is None:
        _data_loader = HotReloadDataLoader()
    
    return _data_loader


def load_all_call_types_optimized(force_reload: bool = False) -> List[Dict]:
    """
    Optimized replacement for load_all_json_call_types.
    
    Features:
    - Hot-reload detection
    - Multi-level caching
    - Performance tracking
    """
    loader = get_data_loader()
    return loader.load_call_types(force_reload=force_reload)


# Maintain backward compatibility with old function
from src.utils.data_loader import (
    get_call_types_by_intent,
    get_all_intent_buckets,
    get_fallback_general_call_type,
    ALL_CALL_TYPES_CACHE,
    INTENT_BUCKETS
)


__all__ = [
    "HotReloadDataLoader",
    "get_data_loader",
    "load_all_call_types_optimized",
    # Re-export from old module for compatibility
    "get_call_types_by_intent",
    "get_all_intent_buckets",
    "get_fallback_general_call_type",
    "ALL_CALL_TYPES_CACHE",
    "INTENT_BUCKETS"
]
