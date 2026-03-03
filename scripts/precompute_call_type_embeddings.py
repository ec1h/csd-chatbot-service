"""
Precompute embeddings for all call types.

Run once after setup (requires network access to download the model the first time):

    python3 scripts/precompute_call_type_embeddings.py

Output files (in data/call_types/):
  call_type_embeddings.npy   – embedding matrix [N × 384]
  call_type_metadata.json    – per-entry metadata aligned with matrix rows
"""

import json
import os
import sys

import numpy as np

# Add project root to path so local imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_all_call_types(data_path: str):
    all_call_types = []
    for root, _dirs, files in os.walk(data_path):
        for file in files:
            if file.endswith(".json") and "call_type" in file.lower():
                filepath = os.path.join(root, file)
                with open(filepath, "r") as f:
                    try:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_call_types.extend(data)
                        else:
                            all_call_types.append(data)
                    except Exception:
                        print(f"  Skipping (parse error): {filepath}")
    return all_call_types


def prepare_text(call_type: dict) -> str:
    """Build a rich text representation of a call type for embedding."""
    parts = []

    description = call_type.get("short_description") or call_type.get("description", "")
    if description:
        parts.append(description)

    issue_type = call_type.get("issue_type", "")
    if issue_type:
        parts.append(issue_type)

    keywords = call_type.get("keywords", [])
    if isinstance(keywords, list):
        parts.extend(keywords[:10])  # limit keyword count

    domain = call_type.get("intent_bucket") or call_type.get("domain", "")
    if domain:
        parts.append(domain)

    return " ".join(parts)


def main():
    data_path = "data/refined data/files"
    output_dir = "data/call_types"
    os.makedirs(output_dir, exist_ok=True)

    print("Loading call types …")
    call_types = load_all_call_types(data_path)
    print(f"  Loaded {len(call_types)} call types")

    print("Loading embedding model (downloads on first run) …")
    from sentence_transformers import SentenceTransformer  # noqa: E402

    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Preparing texts …")
    texts = [prepare_text(ct) for ct in call_types]

    print("Generating embeddings …")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)

    embeddings_path = os.path.join(output_dir, "call_type_embeddings.npy")
    np.save(embeddings_path, embeddings)
    print(f"  Saved embeddings: {embeddings_path}")

    metadata = []
    for i, ct in enumerate(call_types):
        metadata.append(
            {
                "index": i,
                "code": str(ct.get("call_type_code", ct.get("code", ""))),
                "description": ct.get("short_description", ct.get("description", "")),
                "domain": ct.get("intent_bucket", ct.get("domain", "")),
                "category": ct.get("issue_category", ct.get("category", "")),
            }
        )

    metadata_path = os.path.join(output_dir, "call_type_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved metadata:   {metadata_path}")
    print("Done.")


if __name__ == "__main__":
    main()
