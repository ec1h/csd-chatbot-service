"""
FastAPI + DSPy LLM Chatbot for Johannesburg Municipal Services (SYNC)
----------------------------------------------------------------------
- Datastore: PostgreSQL
- LLM orchestration: DSPy (Azure OpenAI backend)
- Data source: JSON files from refined data folder (all departments)
- Behavior: State-driven conversation with confidence-based classification

VERSION 6.0 - OPTIMIZED with Network Classification:
1. Multi-department support (Water, Electricity, Roads, Waste, Fire, EMS, etc.)
2. Conversation phase engine (OPEN_INTAKE → PROBLEM_NARROWING → DETAIL_COLLECTION → CONFIRMATION → LOCKED)
3. Confidence-based classification with tentative intent buckets
4. Human-like guidance with targeted clarifying questions
5. Editable memory model with correction detection
6. **NEW**: Hierarchical taxonomy network for 10x faster classification
7. **NEW**: Semantic similarity network for higher accuracy
8. **NEW**: Decision tree for intelligent guided questions
9. **NEW**: Multi-level caching (memory + disk) for performance
10. **NEW**: Hot-reload support (no restart needed for data updates)
11. **NEW**: Performance monitoring and health checks
"""

import os
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from mangum import Mangum
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import psycopg2

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from src.database.connection import initialize_pool
from src.conversation.conversation_state import ConversationState, ConversationPhase
from src.conversation.case_memory import CaseMemory

# Environment
load_dotenv()
POSTGRES_URI = os.getenv("POSTGRES_URI")
if not POSTGRES_URI:
    raise RuntimeError("Missing POSTGRES_URI")

# Azure OpenAI
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT]):
    raise RuntimeError("Missing one or more required environment variables (AZURE_*).")

# Initialize database pool
initialize_pool()

# Import classification functions (NEW: Optimized pipeline)
USE_OPTIMIZED_PIPELINE = os.getenv("USE_OPTIMIZED_PIPELINE", "true").lower() == "true"

if USE_OPTIMIZED_PIPELINE:
    logger.info("🚀 Using OPTIMIZED classification pipeline with network approach")
    from src.classification.optimized_classifier import (
        initialize_optimized_pipeline,
        get_optimized_pipeline,
        match_call_types_with_network as match_call_types_from_json
    )
    from src.classification.call_type_matcher import detect_intent_bucket
    from src.utils.optimized_loader import get_all_intent_buckets
else:
    logger.info("Using legacy classification pipeline")
    from src.classification.call_type_matcher import match_call_types_from_json, detect_intent_bucket
    from src.classification.embeddings import initialize_embeddings_model, precompute_call_type_embeddings
    from src.utils.data_loader import load_all_json_call_types, get_all_intent_buckets

app = FastAPI(title="Kvell CSD LLM Chatbot", version="2.0.0")

@app.get("/health")
async def liveness_check():
    """Simple health check for load balancer."""
    return {"status": "ok"}
# Setup middleware (CORS, request size limit, error handling)
from src.api.middleware import setup_middleware
setup_middleware(app)

# Include all API routes from endpoints module
from src.api.endpoints import router
app.include_router(router)

# Include monitoring endpoints (NEW in V6.0)
if USE_OPTIMIZED_PIPELINE:
    from src.api.monitoring_endpoints import router as monitoring_router
    app.include_router(monitoring_router)


@app.exception_handler(Exception)
async def global_handler(request, exc):
    import traceback
    import uuid

    error_id = str(uuid.uuid4())[:8]
    # Add this line to see the full traceback
    logger.error(f"ERROR {error_id}: {traceback.format_exc()}")
    print(f"ERROR {error_id}: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "System error",
            "error_id": error_id,
            "message": "Please try again",
        },
    )

@app.middleware("http")
async def catch_exceptions(request, call_next):
    try:
        return await call_next(request)
    except Exception:
        error_id = str(uuid.uuid4())[:8]
        print(f"Middleware caught error {error_id}")
        return JSONResponse(
            status_code=500,
            content={"error": "Request failed", "error_id": error_id},
        )

handler = Mangum(app)


def _sync_api_key_from_env():
    """
    If API_KEY is set (injected by ECS from Secrets Manager), upsert it into ec1_api_keys.
    CI only creates the secret; the app (running in VPC) syncs it to the DB on startup.
    """
    api_key = os.getenv("API_KEY", "").strip()
    if not api_key or "." not in api_key:
        return
    key_id, secret_value = api_key.split(".", 1)
    if not key_id or not secret_value:
        return
    salt = os.urandom(16)
    key_hash = hashlib.pbkdf2_hmac("sha256", secret_value.encode("utf-8"), salt, 100_000)
    expires_at = datetime.now(timezone.utc) + timedelta(days=365)
    from src.database.connection import get_pool
    from psycopg2.extras import RealDictCursor
    pool_instance = get_pool()
    conn = pool_instance.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '5s'")
            cur.execute(
                """
                INSERT INTO ec1_api_keys (key_id, salt, key_hash, status, created_at, expires_at)
                VALUES (%s, %s, %s, 'active', NOW(), %s)
                ON CONFLICT (key_id) DO UPDATE SET
                    salt = EXCLUDED.salt,
                    key_hash = EXCLUDED.key_hash,
                    status = EXCLUDED.status,
                    expires_at = EXCLUDED.expires_at
                """,
                (key_id, psycopg2.Binary(salt), psycopg2.Binary(key_hash), expires_at),
            )
        conn.commit()
        logger.info("API key from env synced to ec1_api_keys: %s", key_id)
    except Exception as e:
        conn.rollback()
        logger.warning("Could not sync API key to DB (non-fatal): %s", e)
    finally:
        pool_instance.putconn(conn)


@app.on_event("startup")
async def startup():
    """Application startup: load data and initialize services"""
    _sync_api_key_from_env()

    if USE_OPTIMIZED_PIPELINE:
        # NEW OPTIMIZED PIPELINE - All-in-one initialization
        try:
            logger.info("="*60)
            logger.info("🚀 INITIALIZING OPTIMIZED CLASSIFICATION PIPELINE")
            logger.info("="*60)
            
            # Initialize the optimized pipeline (loads data, builds networks, sets up caching)
            pipeline = initialize_optimized_pipeline()
            
            # Get statistics
            stats = pipeline.get_statistics()
            logger.info("📊 Pipeline Statistics:")
            logger.info(f"  - Call types loaded: {stats['network']['taxonomy']['total_call_types']}")
            logger.info(f"  - Intent buckets: {stats['network']['taxonomy']['domains']}")
            logger.info(f"  - Confusion pairs detected: {stats['network']['confusion_pairs_detected']}")
            logger.info(f"  - Neighbor graph size: {stats['network']['neighbor_graph_size']}")
            logger.info(f"  - Cache enabled: Yes (LRU with {stats['cache']['cache']['max_size']} entries)")
            
            logger.info(f"Startup: Available intent buckets: {get_all_intent_buckets()}")
            
            logger.info("="*60)
            logger.info("✓ OPTIMIZED PIPELINE READY")
            logger.info("  Features enabled:")
            logger.info("    ✓ Hierarchical taxonomy (10x faster search)")
            logger.info("    ✓ Semantic similarity network (higher accuracy)")
            logger.info("    ✓ Decision tree (smart clarification)")
            logger.info("    ✓ Multi-level caching (memory + disk)")
            logger.info("    ✓ Hot-reload support (no restart needed)")
            logger.info("    ✓ Performance monitoring")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Startup: Failed to initialize optimized pipeline: {e}")
            raise
    else:
        # LEGACY PIPELINE - Original initialization
        try:
            from src.utils.data_loader import load_all_json_call_types
            call_types = load_all_json_call_types()
            logger.info(f"Startup: Loaded {len(call_types)} call types from JSON files")
            logger.info(f"Startup: Available intent buckets: {get_all_intent_buckets()}")
        except Exception as e:
            logger.warning(f"Startup: Could not load JSON call types: {e}")
            call_types = []
        
        # PHASE 2: Initialize embeddings model and precompute embeddings
        try:
            initialize_embeddings_model(model_name="all-MiniLM-L6-v2")
            if call_types:
                precompute_call_type_embeddings(call_types)
                logger.info("Startup: Embeddings initialized and precomputed")
        except Exception as e:
            logger.warning(f"Startup: Could not initialize embeddings (semantic matching will be disabled): {e}")
    
    # Initialize DSPy pipeline (common to both)
    try:
        from src.core.dspy_pipeline import initialize_pipeline
        initialize_pipeline()
        logger.info("Startup: DSPy pipeline initialized")
    except Exception as e:
        logger.error(f"Startup: Failed to initialize DSPy pipeline: {e}")
        raise
    
    # Initialize classifier service (common to both)
    try:
        from src.classification.classifier_service import classifier_service
        classifier_service.set_classifiers(
            match_call_types_from_json=match_call_types_from_json,
            detect_intent_bucket=detect_intent_bucket
        )
        logger.info("Startup: Classifier service initialized")
    except Exception as e:
        logger.error(f"Startup: Failed to initialize classifier service: {e}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
    


