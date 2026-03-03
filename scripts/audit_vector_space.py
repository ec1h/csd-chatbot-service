"""
Audit the TF-IDF vector space for confusable call-type pairs.

Uses the same _TFIDFEngine that the live retrieval system uses, so the
similarity scores here are exactly what the classifier sees at runtime.

Run from project root:
    python3 scripts/audit_vector_space.py

Outputs:
    data/call_types/vector_audit.json   – full results
    Prints top conflicts to stdout
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np

from src.llm.retrieval import CallTypeRetriever, _TFIDFEngine

METADATA_PATH = "data/call_types/call_type_metadata.json"
OUTPUT_PATH = "data/call_types/vector_audit.json"
SIMILARITY_THRESHOLD = 0.70   # pairs above this are potentially confusable


def build_tfidf(metadata):
    documents = [CallTypeRetriever._doc_text(ct) for ct in metadata]
    engine = _TFIDFEngine(documents)
    return engine


def pairwise_similarity(engine, indices):
    """Return upper-triangle cosine similarities for the given index subset."""
    sub = engine._matrix[indices]
    # cosine sim = dot product (vectors are already L2-normalised in _TFIDFEngine)
    sim_matrix = sub @ sub.T
    return sim_matrix


def audit(threshold=SIMILARITY_THRESHOLD):
    with open(METADATA_PATH) as f:
        metadata = json.load(f)

    print(f"Building TF-IDF engine for {len(metadata)} call types …")
    engine = build_tfidf(metadata)

    print("Computing pairwise similarities …")
    indices = list(range(len(metadata)))
    sim_matrix = pairwise_similarity(engine, indices)

    confusable_pairs = []
    for i in range(len(metadata)):
        for j in range(i + 1, len(metadata)):
            sim = float(sim_matrix[i, j])
            if sim >= threshold:
                confusable_pairs.append({
                    "code1": metadata[i].get("code"),
                    "desc1": metadata[i].get("description"),
                    "domain1": metadata[i].get("domain"),
                    "code2": metadata[j].get("code"),
                    "desc2": metadata[j].get("description"),
                    "domain2": metadata[j].get("domain"),
                    "similarity": round(sim, 4),
                })

    confusable_pairs.sort(key=lambda x: -x["similarity"])

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n=== VECTOR AUDIT RESULTS (threshold ≥ {threshold}) ===")
    print(f"Total pairs analysed : {len(metadata) * (len(metadata) - 1) // 2:,}")
    print(f"Confusable pairs     : {len(confusable_pairs)}")

    # Cross-domain confusion is the most dangerous
    cross_domain = [p for p in confusable_pairs if p["domain1"] != p["domain2"]]
    print(f"Cross-domain pairs   : {len(cross_domain)}  ← highest risk")

    print(f"\n{'─'*70}")
    print(f"{'Sim':>5}  {'Code1':<8} {'Desc1':<28} {'Code2':<8} {'Desc2':<28}")
    print(f"{'─'*70}")
    for p in confusable_pairs[:30]:
        marker = " ⚠ cross-domain" if p["domain1"] != p["domain2"] else ""
        print(
            f"{p['similarity']:5.3f}  "
            f"{str(p['code1']):<8} {p['desc1'][:26]:<28} "
            f"{str(p['code2']):<8} {p['desc2'][:26]:<28}"
            f"{marker}"
        )

    print(f"\n=== TOP CROSS-DOMAIN CONFLICTS ===")
    for p in cross_domain[:15]:
        print(
            f"  {p['similarity']:.3f}  [{p['domain1']}] {p['code1']} {p['desc1'][:25]}"
            f"  ↔  [{p['domain2']}] {p['code2']} {p['desc2'][:25]}"
        )

    # ── Targeted: find the specific driver-behaviour vs problem-passengers conflict ──
    print(f"\n=== DRIVER BEHAVIOUR vs PROBLEM PASSENGERS ===")
    driver_codes = {str(ct["code"]) for ct in metadata if "driver" in ct.get("description","").lower() and "behaviour" in ct.get("description","").lower()}
    passenger_codes = {str(ct["code"]) for ct in metadata if "passenger" in ct.get("description","").lower()}
    for p in confusable_pairs:
        if (str(p["code1"]) in driver_codes and str(p["code2"]) in passenger_codes) or \
           (str(p["code2"]) in driver_codes and str(p["code1"]) in passenger_codes):
            print(f"  {p['similarity']:.3f}  {p['code1']} {p['desc1']}  ↔  {p['code2']} {p['desc2']}")

    # ── Save ───────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(
            {
                "threshold": threshold,
                "total_pairs": len(confusable_pairs),
                "cross_domain_pairs": len(cross_domain),
                "pairs": confusable_pairs,
            },
            f, indent=2,
        )
    print(f"\nFull results written → {OUTPUT_PATH}")
    return confusable_pairs


if __name__ == "__main__":
    audit()
