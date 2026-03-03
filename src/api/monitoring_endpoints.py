"""
Monitoring and Admin API Endpoints
===================================
Endpoints for monitoring system performance, health checks, and admin operations.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Monitoring & Admin"])


@router.get("/health")
async def health_check() -> Dict:
    """
    Comprehensive health check endpoint.
    
    Returns system health status including:
    - Overall status (healthy/degraded/unhealthy)
    - Component statuses
    - Performance metrics
    - Issues detected
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized:
            return {
                "status": "uninitialized",
                "message": "Pipeline not yet initialized"
            }
        
        health = pipeline.get_health_status()
        
        return {
            "status": health.get("status", "unknown"),
            "timestamp": health.get("stats", {}).get("timestamp"),
            "issues": health.get("issues", []),
            "components": {
                "database": "operational",
                "classification": health.get("status", "unknown"),
                "cache": "operational"
            },
            "metrics": health.get("stats", {})
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/stats")
async def get_statistics(detailed: bool = Query(False, description="Include detailed statistics")) -> Dict:
    """
    Get comprehensive system statistics.
    
    Query params:
    - detailed: If true, includes detailed breakdown of all components
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        stats = pipeline.get_statistics()
        
        if not detailed:
            # Return summary stats only
            return {
                "summary": {
                    "total_classifications": stats["pipeline"]["classifications"],
                    "avg_time_ms": stats["pipeline"]["avg_time_ms"],
                    "cache_hit_rate": stats["cache"]["cache"]["hit_rate"],
                    "total_call_types": stats["network"]["taxonomy"]["total_call_types"]
                }
            }
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network/taxonomy")
async def get_taxonomy_info() -> Dict:
    """
    Get hierarchical taxonomy structure and statistics.
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized or not pipeline.network_classifier:
            raise HTTPException(status_code=503, detail="Network classifier not initialized")
        
        tax_stats = pipeline.network_classifier.taxonomy.get_statistics()
        
        return {
            "total_call_types": tax_stats["total_call_types"],
            "total_domains": tax_stats["domains"],
            "breakdown": tax_stats["domain_breakdown"],
            "structure": {
                "levels": ["domain", "category", "issue_type", "call_type"],
                "description": "4-level hierarchical classification"
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get taxonomy info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network/similarity/{call_type_code}")
async def get_similar_call_types(
    call_type_code: str,
    min_similarity: float = Query(0.5, ge=0.0, le=1.0, description="Minimum similarity threshold")
) -> Dict:
    """
    Get call types similar to a specific call type.
    
    Useful for:
    - Understanding confusion pairs
    - Debugging misclassifications
    - Improving disambiguation
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized or not pipeline.network_classifier:
            raise HTTPException(status_code=503, detail="Network classifier not initialized")
        
        neighbors = pipeline.network_classifier.similarity_net.get_neighbors(
            call_type_code,
            min_similarity=min_similarity
        )
        
        return {
            "call_type_code": call_type_code,
            "similar_types": neighbors,
            "count": len(neighbors)
        }
        
    except Exception as e:
        logger.error(f"Failed to get similar call types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/confusion-pairs")
async def get_confusion_pairs(limit: int = Query(50, ge=1, le=200)) -> Dict:
    """
    Get pairs of call types that are commonly confused (high similarity).
    
    This helps identify:
    - Call types that need better differentiation
    - Opportunities for better clarifying questions
    - Data quality issues
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized or not pipeline.network_classifier:
            raise HTTPException(status_code=503, detail="Network classifier not initialized")
        
        confusion_pairs = pipeline.network_classifier.similarity_net.confusion_pairs[:limit]
        
        return {
            "total_pairs": len(pipeline.network_classifier.similarity_net.confusion_pairs),
            "pairs": [
                {
                    "code_a": pair[0],
                    "code_b": pair[1],
                    "similarity": pair[2]
                }
                for pair in confusion_pairs
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get confusion pairs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clear")
async def clear_cache(disk: bool = Query(False, description="Also clear disk cache")) -> Dict:
    """
    Clear classification cache.
    
    Use this:
    - After updating call types data
    - When testing new classification logic
    - To force fresh classifications
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized or not pipeline.cached_classifier:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        # Clear memory cache
        pipeline.cached_classifier.clear_cache()
        
        # Clear disk cache if requested
        if disk:
            from src.utils.optimized_loader import get_data_loader
            loader = get_data_loader()
            loader.clear_cache(memory=True, disk=True)
        
        return {
            "status": "success",
            "message": f"Cache cleared (disk: {disk})"
        }
        
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_data() -> Dict:
    """
    Reload call types data (hot-reload).
    
    This reloads data without restarting the application.
    Useful when:
    - Call types JSON files have been updated
    - Testing new call type definitions
    - Recovering from data issues
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        # Check for updates and reload
        reloaded = pipeline.reload_if_changed()
        
        if reloaded:
            stats = pipeline.get_statistics()
            return {
                "status": "reloaded",
                "message": "Data successfully reloaded",
                "call_types": stats["network"]["taxonomy"]["total_call_types"]
            }
        else:
            return {
                "status": "no_changes",
                "message": "No data changes detected"
            }
        
    except Exception as e:
        logger.error(f"Failed to reload data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/report")
async def get_performance_report() -> Dict:
    """
    Get comprehensive performance report.
    
    Includes:
    - Latency percentiles (p50, p95, p99)
    - Throughput (requests/second)
    - Cache effectiveness
    - Component breakdown
    """
    try:
        from src.classification.optimized_classifier import get_optimized_pipeline
        
        pipeline = get_optimized_pipeline()
        
        if not pipeline.initialized:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        stats = pipeline.get_statistics()
        
        return {
            "overview": {
                "total_requests": stats["cache"]["performance"]["total_requests"],
                "throughput_rps": stats["cache"]["performance"]["throughput_rps"],
                "error_rate": stats["cache"]["performance"]["error_rate"]
            },
            "latency": stats["cache"]["performance"]["latency"],
            "cache": {
                "hit_rate": stats["cache"]["cache"]["hit_rate"],
                "size": stats["cache"]["cache"]["size"],
                "evictions": stats["cache"]["cache"]["evictions"]
            },
            "network": {
                "avg_candidates_considered": stats["network"]["avg_candidates_considered"],
                "avg_classification_time_ms": stats["network"]["avg_classification_time_ms"]
            },
            "data_loader": stats["data_loader"]
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Add router to main app (done in app.py)
__all__ = ["router"]
