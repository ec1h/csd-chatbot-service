"""
Call Type Network - Advanced Classification System
===================================================
Multi-level classification using:
1. Hierarchical taxonomy (domain -> category -> issue -> call type)
2. Embedding similarity network (semantic relationships)
3. Decision tree (guided clarification)
4. Performance optimization (caching, pre-computation)

VERSION: 1.0
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import pickle

logger = logging.getLogger(__name__)


class HierarchicalTaxonomy:
    """
    Builds a hierarchical taxonomy of call types for fast narrowing.
    
    Structure:
        Domain (intent_bucket) -> Category (issue_category) -> Issue Group -> Call Types
    
    This reduces search space from 612 to ~9 -> ~5 -> ~3 -> specific call types
    """
    
    def __init__(self, call_types: List[Dict]):
        self.call_types = call_types
        self.taxonomy = self._build_taxonomy()
        self.reverse_index = self._build_reverse_index()
        
    def _build_taxonomy(self) -> Dict:
        """Build hierarchical taxonomy from call types"""
        taxonomy = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        
        for ct in self.call_types:
            domain = ct.get("intent_bucket", "general").lower()
            category = ct.get("issue_category", "general").lower()
            issue_type = ct.get("issue_type", "general").lower()
            
            taxonomy[domain][category][issue_type].append(ct)
        
        # Convert to regular dicts
        result = {}
        for domain, categories in taxonomy.items():
            result[domain] = {}
            for category, issues in categories.items():
                result[domain][category] = dict(issues)
        
        return result
    
    def _build_reverse_index(self) -> Dict[str, Dict]:
        """Build reverse index for fast lookups"""
        index = {}
        for ct in self.call_types:
            code = str(ct.get("call_type_code"))
            index[code] = {
                "domain": ct.get("intent_bucket", "general").lower(),
                "category": ct.get("issue_category", "general").lower(),
                "issue_type": ct.get("issue_type", "general").lower()
            }
        return index
    
    def get_candidates_by_path(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        issue_type: Optional[str] = None
    ) -> List[Dict]:
        """Get call types by hierarchical path"""
        if not domain:
            # No domain - return all
            return self.call_types
        
        if domain not in self.taxonomy:
            return []
        
        if not category:
            # Domain only - return all in domain
            candidates = []
            for cat_dict in self.taxonomy[domain].values():
                for issue_list in cat_dict.values():
                    candidates.extend(issue_list)
            return candidates
        
        if category not in self.taxonomy[domain]:
            return []
        
        if not issue_type:
            # Domain + category - return all in category
            candidates = []
            for issue_list in self.taxonomy[domain][category].values():
                candidates.extend(issue_list)
            return candidates
        
        # Full path specified
        return self.taxonomy[domain][category].get(issue_type, [])
    
    def get_statistics(self) -> Dict:
        """Get taxonomy statistics"""
        stats = {
            "total_call_types": len(self.call_types),
            "domains": len(self.taxonomy),
            "domain_breakdown": {}
        }
        
        for domain, categories in self.taxonomy.items():
            total = sum(
                len(call_types)
                for cat_dict in categories.values()
                for call_types in cat_dict.values()
            )
            stats["domain_breakdown"][domain] = {
                "total": total,
                "categories": len(categories)
            }
        
        return stats


class SimilarityNetwork:
    """
    Embedding-based similarity network with pre-computed relationships.
    
    Pre-computes:
    - Pairwise similarities between all call types
    - Nearest neighbors for each call type
    - Confusion matrices (commonly confused pairs)
    - Cluster assignments
    """
    
    def __init__(self, call_types: List[Dict], embeddings: Dict[str, np.ndarray]):
        self.call_types = call_types
        self.embeddings = embeddings
        self.code_to_idx = {str(ct.get("call_type_code")): i for i, ct in enumerate(call_types)}
        self.idx_to_code = {i: str(ct.get("call_type_code")) for i, ct in enumerate(call_types)}
        
        # Pre-compute similarity matrix
        self.similarity_matrix = self._compute_similarity_matrix()
        
        # Build neighbor graph
        self.neighbor_graph = self._build_neighbor_graph()
        
        # Detect confusion pairs
        self.confusion_pairs = self._detect_confusion_pairs()
    
    def _compute_similarity_matrix(self) -> np.ndarray:
        """Pre-compute pairwise similarities for all call types"""
        n = len(self.call_types)
        similarity_matrix = np.zeros((n, n))
        
        # Build embedding matrix
        embedding_codes = []
        embeddings_list = []
        
        for ct in self.call_types:
            code = str(ct.get("call_type_code"))
            if code in self.embeddings:
                embedding_codes.append(code)
                embeddings_list.append(self.embeddings[code])
        
        if not embeddings_list:
            logger.warning("No embeddings available for similarity computation")
            return similarity_matrix
        
        # Stack embeddings into matrix
        embedding_matrix = np.stack(embeddings_list)
        
        # Compute pairwise cosine similarities (dot product for normalized embeddings)
        similarity_matrix = np.dot(embedding_matrix, embedding_matrix.T)
        
        # Map back to full matrix
        full_matrix = np.zeros((n, n))
        for i, code_i in enumerate(embedding_codes):
            idx_i = self.code_to_idx[code_i]
            for j, code_j in enumerate(embedding_codes):
                idx_j = self.code_to_idx[code_j]
                full_matrix[idx_i, idx_j] = similarity_matrix[i, j]
        
        logger.info(f"Computed similarity matrix: {full_matrix.shape}")
        return full_matrix
    
    def _build_neighbor_graph(self, k: int = 10) -> Dict[str, List[Dict]]:
        """Build k-nearest neighbor graph for each call type"""
        graph = {}
        
        for i, ct in enumerate(self.call_types):
            code = str(ct.get("call_type_code"))
            
            # Get similarities for this call type
            similarities = self.similarity_matrix[i]
            
            # Find top k neighbors (excluding self)
            neighbor_indices = np.argsort(similarities)[::-1][1:k+1]
            
            neighbors = []
            for idx in neighbor_indices:
                if similarities[idx] > 0:  # Only include if there's actual similarity
                    neighbor_code = self.idx_to_code[idx]
                    neighbor_ct = self.call_types[idx]
                    neighbors.append({
                        "code": neighbor_code,
                        "description": neighbor_ct.get("short_description"),
                        "similarity": float(similarities[idx]),
                        "intent_bucket": neighbor_ct.get("intent_bucket")
                    })
            
            graph[code] = neighbors
        
        logger.info(f"Built neighbor graph with {len(graph)} nodes")
        return graph
    
    def _detect_confusion_pairs(self, threshold: float = 0.75) -> List[Tuple[str, str, float]]:
        """Detect call types that are commonly confused (high similarity)"""
        confusion_pairs = []
        n = len(self.call_types)
        
        for i in range(n):
            for j in range(i + 1, n):
                sim = self.similarity_matrix[i, j]
                
                # High similarity = potential confusion
                if sim > threshold:
                    code_i = self.idx_to_code[i]
                    code_j = self.idx_to_code[j]
                    
                    # Only consider if they're in the same domain
                    ct_i = self.call_types[i]
                    ct_j = self.call_types[j]
                    
                    if ct_i.get("intent_bucket") == ct_j.get("intent_bucket"):
                        confusion_pairs.append((code_i, code_j, float(sim)))
        
        confusion_pairs.sort(key=lambda x: x[2], reverse=True)
        logger.info(f"Detected {len(confusion_pairs)} confusion pairs")
        return confusion_pairs
    
    def get_neighbors(self, call_type_code: str, min_similarity: float = 0.5) -> List[Dict]:
        """Get similar call types"""
        if call_type_code not in self.neighbor_graph:
            return []
        
        neighbors = self.neighbor_graph[call_type_code]
        return [n for n in neighbors if n["similarity"] >= min_similarity]
    
    def get_similarity(self, code_a: str, code_b: str) -> float:
        """Get similarity between two call types"""
        if code_a not in self.code_to_idx or code_b not in self.code_to_idx:
            return 0.0
        
        idx_a = self.code_to_idx[code_a]
        idx_b = self.code_to_idx[code_b]
        
        return float(self.similarity_matrix[idx_a, idx_b])
    
    def find_most_similar(
        self,
        user_text: str,
        candidates: List[Dict],
        embeddings_cache: Dict[str, np.ndarray],
        top_k: int = 10
    ) -> List[Tuple[Dict, float]]:
        """Find most similar call types to user text from candidates"""
        from src.classification.embeddings import _model
        
        if _model is None or not embeddings_cache:
            return [(ct, 0.0) for ct in candidates[:top_k]]
        
        # Encode user text
        user_embedding = _model.encode(user_text, normalize_embeddings=True)
        
        # Score each candidate
        scored = []
        for ct in candidates:
            code = str(ct.get("call_type_code"))
            if code in embeddings_cache:
                similarity = float(np.dot(user_embedding, embeddings_cache[code]))
                scored.append((ct, similarity))
            else:
                scored.append((ct, 0.0))
        
        # Sort by similarity
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class DecisionTree:
    """
    Decision tree for guided classification with targeted questions.
    
    Uses the taxonomy and similarity network to generate smart questions
    that best disambiguate between similar call types.
    """
    
    def __init__(self, taxonomy: HierarchicalTaxonomy, similarity_net: SimilarityNetwork):
        self.taxonomy = taxonomy
        self.similarity_net = similarity_net
        self.decision_paths = self._build_decision_paths()
    
    def _build_decision_paths(self) -> Dict:
        """Build decision paths for each domain"""
        paths = {}
        
        for domain in self.taxonomy.taxonomy.keys():
            paths[domain] = self._build_domain_path(domain)
        
        return paths
    
    def _build_domain_path(self, domain: str) -> Dict:
        """Build decision path for a specific domain"""
        categories = list(self.taxonomy.taxonomy[domain].keys())
        
        # Build questions for each level
        path = {
            "domain": domain,
            "category_question": self._generate_category_question(domain, categories),
            "categories": {}
        }
        
        for category in categories:
            issue_types = list(self.taxonomy.taxonomy[domain][category].keys())
            path["categories"][category] = {
                "issue_question": self._generate_issue_question(domain, category, issue_types),
                "issue_types": issue_types
            }
        
        return path
    
    def _generate_category_question(self, domain: str, categories: List[str]) -> str:
        """Generate question to determine category"""
        # Domain-specific questions
        questions = {
            "water": "Is this about water supply/pressure, sewage/drainage, or billing?",
            "electricity": "Is this about power outages, street lighting, prepaid meters, or billing?",
            "roads": "Is this about road surface, traffic signals, signs, or infrastructure?",
            "waste": "Is this about bin collection, illegal dumping, or recycling?",
            "emergency": "What type of emergency? Fire, medical, rescue, or hazmat?",
            "transport": "Is this about bus service, routes, cards, or vehicle condition?",
            "health": "Is this about pest control, noise, food safety, or pollution?",
            "billing": "Is this about account queries, disputes, payments, or refunds?",
            "general": "What type of enquiry is this?"
        }
        
        return questions.get(domain, f"What aspect of {domain} is this about?")
    
    def _generate_issue_question(self, domain: str, category: str, issue_types: List[str]) -> str:
        """Generate question to determine specific issue"""
        if len(issue_types) <= 1:
            return "Can you provide more details about the issue?"
        
        # Generic question based on issue types
        return f"Which best describes your issue: {', '.join(issue_types[:3])}?"
    
    def get_next_question(
        self,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        candidates: Optional[List[Dict]] = None
    ) -> Dict:
        """Get next clarification question based on current state"""
        if not domain:
            return {
                "question": "What service is this about?",
                "type": "domain_selection",
                "options": list(self.taxonomy.taxonomy.keys())
            }
        
        if domain not in self.decision_paths:
            return {"question": "Can you provide more details?", "type": "open_ended"}
        
        path = self.decision_paths[domain]
        
        if not category:
            return {
                "question": path["category_question"],
                "type": "category_selection",
                "options": list(path["categories"].keys())
            }
        
        if category in path["categories"]:
            cat_info = path["categories"][category]
            return {
                "question": cat_info["issue_question"],
                "type": "issue_selection",
                "options": cat_info["issue_types"]
            }
        
        # If we have candidates, generate disambiguation question
        if candidates and len(candidates) >= 2:
            return self._generate_disambiguation_question(candidates[:2])
        
        return {"question": "Can you provide more details?", "type": "open_ended"}
    
    def _generate_disambiguation_question(self, candidates: List[Dict]) -> Dict:
        """Generate question to disambiguate between similar call types"""
        ct1 = candidates[0]
        ct2 = candidates[1]
        
        # Extract distinguishing keywords
        kw1 = set(ct1.get("keywords", []))
        kw2 = set(ct2.get("keywords", []))
        
        unique1 = kw1 - kw2
        unique2 = kw2 - kw1
        
        if unique1 and unique2:
            # Use distinguishing keywords
            hint1 = list(unique1)[:2]
            hint2 = list(unique2)[:2]
            
            return {
                "question": f"Is this more about {', '.join(hint1)} or {', '.join(hint2)}?",
                "type": "disambiguation",
                "options": [
                    ct1.get("short_description"),
                    ct2.get("short_description")
                ]
            }
        
        # Fallback to descriptions
        return {
            "question": f"Which better describes your issue?",
            "type": "disambiguation",
            "options": [
                ct1.get("short_description"),
                ct2.get("short_description")
            ]
        }


class CallTypeNetworkClassifier:
    """
    Unified network-based classifier combining all approaches.
    
    Features:
    - Hierarchical search (fast candidate reduction)
    - Semantic similarity (accurate ranking)
    - Guided questions (better disambiguation)
    - Performance monitoring
    - Caching
    """
    
    def __init__(
        self,
        call_types: List[Dict],
        embeddings: Dict[str, np.ndarray],
        cache_dir: Optional[Path] = None
    ):
        self.call_types = call_types
        self.embeddings = embeddings
        self.cache_dir = cache_dir or Path(__file__).parent / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        
        # Performance tracking
        self.stats = {
            "total_classifications": 0,
            "hierarchical_hits": 0,
            "semantic_rescues": 0,
            "avg_candidates_considered": 0.0,
            "avg_classification_time_ms": 0.0
        }
        
        # Build networks
        logger.info("Building hierarchical taxonomy...")
        self.taxonomy = HierarchicalTaxonomy(call_types)
        
        logger.info("Building similarity network...")
        self.similarity_net = SimilarityNetwork(call_types, embeddings)
        
        logger.info("Building decision tree...")
        self.decision_tree = DecisionTree(self.taxonomy, self.similarity_net)
        
        # Cache frequently accessed data
        self._domain_cache = {}
        self._category_cache = {}
        
        logger.info("Network classifier initialized successfully")
        logger.info(f"Taxonomy: {self.taxonomy.get_statistics()}")
    
    def classify(
        self,
        user_text: str,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        conversation_history: Optional[List[str]] = None,
        return_neighbors: bool = False
    ) -> Dict:
        """
        Classify user text using network approach.
        
        Args:
            user_text: User's message
            domain: Pre-detected domain (intent bucket)
            category: Pre-detected category
            conversation_history: Previous messages for context
            return_neighbors: Include similar call types in result
            
        Returns:
            Classification result with candidates, confidence, and optional neighbors
        """
        start_time = datetime.now()
        
        # Step 1: Get candidates using taxonomy (hierarchical filtering)
        candidates = self.taxonomy.get_candidates_by_path(domain, category)
        
        if not candidates:
            # Fallback to all call types
            candidates = self.call_types
        
        self.stats["avg_candidates_considered"] = (
            (self.stats["avg_candidates_considered"] * self.stats["total_classifications"] + len(candidates)) /
            (self.stats["total_classifications"] + 1)
        )
        
        # Step 2: Rank candidates using semantic similarity
        ranked_candidates = self.similarity_net.find_most_similar(
            user_text=user_text,
            candidates=candidates,
            embeddings_cache=self.embeddings,
            top_k=10
        )
        
        # Step 3: Build result
        if not ranked_candidates:
            result = {
                "classified": False,
                "confidence": 0.0,
                "candidates": [],
                "needs_clarification": True,
                "question": self.decision_tree.get_next_question(domain, category)
            }
        else:
            top_match, top_score = ranked_candidates[0]
            
            result = {
                "classified": top_score >= 0.5,
                "call_type_code": top_match.get("call_type_code"),
                "description": top_match.get("short_description"),
                "confidence": top_score,
                "candidates": [
                    {
                        "code": ct.get("call_type_code"),
                        "description": ct.get("short_description"),
                        "score": score
                    }
                    for ct, score in ranked_candidates[:5]
                ],
                "needs_clarification": top_score < 0.7 or (
                    len(ranked_candidates) >= 2 and
                    ranked_candidates[1][1] > top_score - 0.1
                )
            }
            
            # Add clarification question if needed
            if result["needs_clarification"]:
                result["question"] = self.decision_tree.get_next_question(
                    domain,
                    category,
                    [ct for ct, _ in ranked_candidates[:2]]
                )
            
            # Add neighbors if requested
            if return_neighbors:
                code = str(top_match.get("call_type_code"))
                neighbors = self.similarity_net.get_neighbors(code, min_similarity=0.6)
                result["neighbors"] = neighbors[:5]
        
        # Update stats
        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        self.stats["total_classifications"] += 1
        self.stats["avg_classification_time_ms"] = (
            (self.stats["avg_classification_time_ms"] * (self.stats["total_classifications"] - 1) + elapsed) /
            self.stats["total_classifications"]
        )
        
        return result
    
    def get_statistics(self) -> Dict:
        """Get performance statistics"""
        tax_stats = self.taxonomy.get_statistics()
        
        return {
            **self.stats,
            "taxonomy": tax_stats,
            "confusion_pairs_detected": len(self.similarity_net.confusion_pairs),
            "neighbor_graph_size": len(self.similarity_net.neighbor_graph)
        }
    
    def save_cache(self):
        """Save pre-computed networks to disk for faster startup"""
        cache_file = self.cache_dir / "network_cache.pkl"
        
        cache_data = {
            "similarity_matrix": self.similarity_net.similarity_matrix,
            "neighbor_graph": self.similarity_net.neighbor_graph,
            "confusion_pairs": self.similarity_net.confusion_pairs,
            "taxonomy": self.taxonomy.taxonomy,
            "timestamp": datetime.now().isoformat()
        }
        
        with open(cache_file, 'wb') as f:
            pickle.dump(cache_data, f)
        
        logger.info(f"Saved network cache to {cache_file}")
    
    def load_cache(self) -> bool:
        """Load pre-computed networks from disk"""
        cache_file = self.cache_dir / "network_cache.pkl"
        
        if not cache_file.exists():
            return False
        
        try:
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            self.similarity_net.similarity_matrix = cache_data["similarity_matrix"]
            self.similarity_net.neighbor_graph = cache_data["neighbor_graph"]
            self.similarity_net.confusion_pairs = cache_data["confusion_pairs"]
            self.taxonomy.taxonomy = cache_data["taxonomy"]
            
            logger.info(f"Loaded network cache from {cache_file}")
            logger.info(f"Cache timestamp: {cache_data.get('timestamp', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            return False


# Global instance (initialized in app startup)
_network_classifier: Optional[CallTypeNetworkClassifier] = None


def get_network_classifier() -> Optional[CallTypeNetworkClassifier]:
    """Get global network classifier instance"""
    return _network_classifier


def initialize_network_classifier(
    call_types: List[Dict],
    embeddings: Dict[str, np.ndarray]
) -> CallTypeNetworkClassifier:
    """Initialize global network classifier"""
    global _network_classifier
    
    _network_classifier = CallTypeNetworkClassifier(call_types, embeddings)
    
    # Try to load cache for faster startup
    if _network_classifier.load_cache():
        logger.info("Network classifier loaded from cache")
    else:
        logger.info("Building network classifier from scratch")
        # Save cache for next time
        _network_classifier.save_cache()
    
    return _network_classifier


__all__ = [
    "HierarchicalTaxonomy",
    "SimilarityNetwork",
    "DecisionTree",
    "CallTypeNetworkClassifier",
    "get_network_classifier",
    "initialize_network_classifier"
]
