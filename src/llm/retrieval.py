"""
Retrieval layer for finding relevant call types.

Two-stage pipeline:
  Stage 1 – Domain filtering : narrow ~610 call types to ~20 domain matches
  Stage 2 – TF-IDF ranking   : rank the 20 by TF-IDF cosine similarity

Stage 2 uses a pure-numpy TF-IDF implementation built at init time from the
call type metadata.  No sentence-transformers or external model downloads are
required.  If pre-computed neural embeddings are available in
``data/call_types/call_type_embeddings.npy`` they are used instead
(run ``scripts/precompute_call_type_embeddings.py`` to generate them).
"""

import json
import logging
import math
import os
import re
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "call_types")
_EMBEDDINGS_PATH = os.path.join(_DATA_DIR, "call_type_embeddings.npy")
_METADATA_PATH = os.path.join(_DATA_DIR, "call_type_metadata.json")
_HIERARCHY_PATH = os.path.join(_DATA_DIR, "domain_hierarchy.json")


# ---------------------------------------------------------------------------
# TF-IDF engine (pure numpy + stdlib, no external model)
# ---------------------------------------------------------------------------

class _TFIDFEngine:
    """Lightweight TF-IDF similarity engine backed by numpy."""

    # Common English stop-words to filter out
    _STOPWORDS = {
        "a", "an", "and", "are", "as", "at", "be", "been", "by", "for",
        "from", "has", "have", "he", "i", "in", "is", "it", "its", "of",
        "on", "or", "that", "the", "their", "there", "they", "this", "to",
        "was", "were", "will", "with", "my", "me", "we", "our", "not",
        "no", "do", "can", "at", "about",
    }

    def __init__(self, documents: List[str]):
        self._tokenize_re = re.compile(r"[a-z0-9]+")
        self._vocab: Dict[str, int] = {}
        self._idf: np.ndarray
        self._matrix: np.ndarray  # shape: (N_docs, V)

        tokens_per_doc = [self._tokenize(doc) for doc in documents]
        self._build_vocab(tokens_per_doc)
        self._idf = self._compute_idf(tokens_per_doc, len(documents))
        self._matrix = self._build_matrix(tokens_per_doc)
        logger.info(
            "TF-IDF engine built: %d docs × %d terms",
            len(documents),
            len(self._vocab),
        )

    def _tokenize(self, text: str) -> List[str]:
        words = self._tokenize_re.findall(text.lower())
        return [w for w in words if w not in self._STOPWORDS and len(w) > 1]

    def _build_vocab(self, tokens_per_doc: List[List[str]]) -> None:
        word_doc_freq: Dict[str, int] = {}
        for tokens in tokens_per_doc:
            for word in set(tokens):
                word_doc_freq[word] = word_doc_freq.get(word, 0) + 1
        # Include all terms that appear in at least 1 document
        for word, df in word_doc_freq.items():
            if word not in self._vocab:
                self._vocab[word] = len(self._vocab)

    def _compute_idf(self, tokens_per_doc: List[List[str]], n_docs: int) -> np.ndarray:
        idf = np.zeros(len(self._vocab))
        for tokens in tokens_per_doc:
            for word in set(tokens):
                if word in self._vocab:
                    idf[self._vocab[word]] += 1
        # Smooth IDF: log((N+1)/(df+1)) + 1
        idf = np.log((n_docs + 1) / (idf + 1)) + 1.0
        return idf

    def _vectorize(self, tokens: List[str]) -> np.ndarray:
        vec = np.zeros(len(self._vocab))
        for word in tokens:
            if word in self._vocab:
                vec[self._vocab[word]] += 1
        # Apply IDF and L2-normalise
        vec = vec * self._idf
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def _build_matrix(self, tokens_per_doc: List[List[str]]) -> np.ndarray:
        matrix = np.vstack([self._vectorize(t) for t in tokens_per_doc])
        return matrix

    def score(self, query: str, indices: List[int]) -> np.ndarray:
        """Return cosine similarity between *query* and docs at *indices*."""
        q_vec = self._vectorize(self._tokenize(query))
        sub_matrix = self._matrix[indices]
        similarities = sub_matrix @ q_vec
        return similarities


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

class CallTypeRetriever:
    """Retrieve the most relevant call types for a user message."""

    def __init__(self):
        # Load metadata (always required)
        with open(_METADATA_PATH, "r") as f:
            self.metadata: List[Dict] = json.load(f)

        # Load hierarchy (always required)
        with open(_HIERARCHY_PATH, "r") as f:
            self.hierarchy: Dict = json.load(f)

        # Build TF-IDF engine from metadata (primary ranking method)
        documents = [self._doc_text(ct) for ct in self.metadata]
        self._tfidf = _TFIDFEngine(documents)

        # Pre-computed neural embeddings (optional – higher accuracy when available)
        self._embeddings: Optional[np.ndarray] = None
        self._embedding_model = None
        if os.path.exists(_EMBEDDINGS_PATH):
            try:
                self._embeddings = np.load(_EMBEDDINGS_PATH)
                logger.info(
                    "Loaded pre-computed neural embeddings: shape=%s",
                    self._embeddings.shape,
                )
            except Exception as exc:
                logger.warning("Could not load neural embeddings (%s) – using TF-IDF", exc)

        # Domain detector (lazy init)
        self._domain_detector = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _doc_text(ct: Dict) -> str:
        """Build a rich text document from a call type metadata entry."""
        parts = []
        if ct.get("description"):
            parts.append(ct["description"].lower())
        if ct.get("issue_type"):
            parts.append(ct["issue_type"].lower())
        if ct.get("domain"):
            parts.append(ct["domain"])
        if ct.get("category"):
            parts.append(ct["category"])
        # Include keywords (list of strings)
        for kw in ct.get("keywords", [])[:15]:
            if isinstance(kw, str):
                parts.append(kw.lower())
        # Include example utterances for extra recall
        for utt in ct.get("example_utterances", [])[:3]:
            if isinstance(utt, str):
                parts.append(utt.lower())
        return " ".join(parts)

    def _get_domain_detector(self):
        if self._domain_detector is None:
            from src.classification.domain_detector import DomainDetector  # noqa: PLC0415

            self._domain_detector = DomainDetector(_HIERARCHY_PATH)
        return self._domain_detector

    def _get_embedding_model(self):
        """Lazy-load the sentence-transformer model for query encoding."""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Loaded SentenceTransformer model for live query encoding")
            except Exception as exc:
                logger.warning("Cannot load SentenceTransformer: %s", exc)
        return self._embedding_model

    # ------------------------------------------------------------------
    # Stage 1: Domain filtering
    # ------------------------------------------------------------------

    def retrieve_by_domain(self, message: str, top_k: int = 20) -> List[Dict]:
        """Return candidates filtered by detected domain.

        All entries from the primary domain are returned (the TF-IDF stage
        ranks and caps to ``top_k``).  If the domain bucket is very small,
        candidates from the secondary domain are appended as padding.
        The ``top_k`` parameter is only used as a *minimum* padding target.
        """
        detector = self._get_domain_detector()
        domains = detector.detect(message)

        if not domains:
            return self.metadata  # no domain signal: score all entries

        primary_domain = domains[0]
        domain_candidates = [
            ct for ct in self.metadata
            if ct.get("domain", "").lower() == primary_domain
        ]

        # Pad with secondary domain if primary is very small
        if len(domain_candidates) < top_k and len(domains) > 1:
            secondary_domain = domains[1]
            seen_codes = {ct["code"] for ct in domain_candidates}
            secondary = [
                ct for ct in self.metadata
                if ct.get("domain", "").lower() == secondary_domain
                and ct["code"] not in seen_codes
            ]
            domain_candidates.extend(secondary)

        return domain_candidates

    # ------------------------------------------------------------------
    # Stage 2: Similarity ranking
    # ------------------------------------------------------------------

    def retrieve_by_similarity(
        self, message: str, candidates: List[Dict], top_k: int = 10
    ) -> List[Dict]:
        """Rank *candidates* by similarity to *message* and return top *top_k*."""

        # --- Neural embedding ranking (if available) ---
        if self._embeddings is not None:
            model = self._get_embedding_model()
            if model is not None:
                indices = [c["index"] for c in candidates]
                candidate_embeddings = self._embeddings[indices]
                message_embedding = model.encode([message])
                similarities = np.dot(candidate_embeddings, message_embedding.T).flatten()
                sorted_idx = np.argsort(similarities)[::-1][:top_k]
                results = []
                for idx in sorted_idx:
                    entry = candidates[idx].copy()
                    entry["similarity"] = float(similarities[idx])
                    results.append(entry)
                return results

        # --- TF-IDF ranking (primary method when neural embeddings are absent) ---
        indices = [c["index"] for c in candidates]
        scores = self._tfidf.score(message, indices)
        sorted_idx = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in sorted_idx:
            entry = candidates[idx].copy()
            entry["similarity"] = float(scores[idx])
            results.append(entry)
        return results

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def retrieve(self, message: str, top_k: int = 10) -> List[Dict]:
        """Run the full two-stage retrieval pipeline."""
        domain_candidates = self.retrieve_by_domain(message, top_k=20)
        return self.retrieve_by_similarity(message, domain_candidates, top_k=top_k)

    def format_candidates_for_llm(self, candidates: List[Dict]) -> str:
        """Format candidate list as a numbered string for an LLM prompt."""
        lines = ["Relevant call types:"]
        for i, ct in enumerate(candidates, 1):
            lines.append(f"{i}. [{ct['code']}] {ct.get('description', '')}")
        return "\n".join(lines)
