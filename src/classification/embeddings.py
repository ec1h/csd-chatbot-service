"""
Embedding-based semantic matching for call type classification.

Uses sentence transformers to find semantically similar call types.

The model name/path can be overridden at runtime via the
`EMBEDDINGS_MODEL_NAME` environment variable. This allows you to
plug in a fine-tuned SentenceTransformer (see `scripts/finetune_embeddings.py`).
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Global model and embeddings cache
_model = None
_call_type_embeddings: Dict[str, np.ndarray] = {}


def initialize_embeddings_model(model_name: str = "all-MiniLM-L6-v2"):
    """
    Initialize the sentence transformer model.
    Should be called once at application startup.
    
    Args:
        model_name: Name of the sentence transformer model to use
    """
    global _model
    try:
        from sentence_transformers import SentenceTransformer

        effective_name = os.getenv("EMBEDDINGS_MODEL_NAME", model_name)
        _model = SentenceTransformer(effective_name)
        logger.info(f"Initialized embedding model: {effective_name}")
    except ImportError:
        logger.warning("sentence-transformers not installed. Semantic matching will be disabled.")
        _model = None
    except Exception as e:
        logger.error(f"Failed to initialize embedding model: {e}")
        _model = None


def precompute_call_type_embeddings(call_types: List[Dict]) -> Dict[str, np.ndarray]:
    """
    Pre-compute embeddings for all call type descriptions.
    Should be called once at application startup after loading call types.
    
    Args:
        call_types: List of call type dictionaries
        
    Returns:
        Dictionary mapping call_type_code to embedding vector
    """
    global _call_type_embeddings, _model
    
    if _model is None:
        logger.warning("Embedding model not initialized. Skipping precomputation.")
        return {}
    
    if _call_type_embeddings:
        logger.info(f"Using cached embeddings for {len(_call_type_embeddings)} call types")
        return _call_type_embeddings
    
    embeddings = {}
    
    try:
        for ct in call_types:
            call_type_code = str(ct.get("call_type_code", ""))
            if not call_type_code:
                continue
            
            # Build description text from multiple fields
            desc_parts = []
            if ct.get("short_description"):
                desc_parts.append(ct["short_description"])
            if ct.get("description"):
                desc_parts.append(ct["description"])
            if ct.get("issue_type"):
                desc_parts.append(ct["issue_type"])
            
            desc_text = " ".join(desc_parts)
            if not desc_text.strip():
                continue
            
            # Compute embedding
            embedding = _model.encode(desc_text, normalize_embeddings=True)
            embeddings[call_type_code] = embedding
        
        _call_type_embeddings = embeddings
        logger.info(f"Precomputed embeddings for {len(embeddings)} call types")
        
    except Exception as e:
        logger.error(f"Failed to precompute embeddings: {e}")
        return {}
    
    return embeddings


def get_semantic_matches(
    user_text: str,
    call_type_embeddings: Optional[Dict[str, np.ndarray]] = None,
    top_k: int = 5
) -> List[Tuple[str, float]]:
    """
    Find semantically similar call types using embeddings.
    
    Args:
        user_text: User's input text
        call_type_embeddings: Dictionary of call_type_code -> embedding (uses cache if None)
        top_k: Number of top matches to return
        
    Returns:
        List of (call_type_code, similarity_score) tuples, sorted by score descending
    """
    global _model, _call_type_embeddings
    
    if _model is None:
        logger.debug("Embedding model not available. Skipping semantic matching.")
        return []
    
    # Use cached embeddings if not provided
    if call_type_embeddings is None:
        call_type_embeddings = _call_type_embeddings
    
    if not call_type_embeddings:
        logger.debug("No call type embeddings available. Skipping semantic matching.")
        return []
    
    try:
        # Encode user text
        user_embedding = _model.encode(user_text, normalize_embeddings=True)
        
        # Compute cosine similarity with all call types
        scores = []
        for code, emb in call_type_embeddings.items():
            # Cosine similarity (dot product for normalized embeddings)
            similarity = float(np.dot(user_embedding, emb))
            scores.append((code, similarity))
        
        # Sort by similarity descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_k]
        
    except Exception as e:
        logger.error(f"Error in semantic matching: {e}")
        return []


def get_semantic_score(
    user_text: str,
    call_type_code: str,
    call_type_embeddings: Optional[Dict[str, np.ndarray]] = None
) -> float:
    """
    Get semantic similarity score for a specific call type.
    
    Args:
        user_text: User's input text
        call_type_code: Call type code to score
        call_type_embeddings: Dictionary of call_type_code -> embedding (uses cache if None)
        
    Returns:
        Similarity score between 0 and 1
    """
    global _model, _call_type_embeddings
    
    if _model is None:
        return 0.0
    
    if call_type_embeddings is None:
        call_type_embeddings = _call_type_embeddings
    
    if not call_type_embeddings or call_type_code not in call_type_embeddings:
        return 0.0
    
    try:
        user_embedding = _model.encode(user_text, normalize_embeddings=True)
        call_type_embedding = call_type_embeddings[call_type_code]
        
        # Cosine similarity (normalized embeddings)
        similarity = float(np.dot(user_embedding, call_type_embedding))
        
        # Normalize to 0-1 range (cosine similarity is already -1 to 1, but with normalized embeddings it's 0-1)
        return max(0.0, min(1.0, similarity))
        
    except Exception as e:
        logger.error(f"Error computing semantic score: {e}")
        return 0.0


__all__ = [
    "initialize_embeddings_model",
    "precompute_call_type_embeddings",
    "get_semantic_matches",
    "get_semantic_score",
]
