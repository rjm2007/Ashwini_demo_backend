"""BM25-style sparse vectors for Qdrant hybrid search."""

import re
from collections import Counter

from qdrant_client.models import SparseVector

STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "because", "but", "and",
    "or", "if", "while", "that", "this", "it", "its", "they", "them",
    "their", "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "page", "see", "also", "may", "must", "per", "any", "which",
})


class BM25SparseEncoder:
    def __init__(self, vocab_size: int = 262144, k1: float = 1.2, b: float = 0.75):
        self.vocab_size = vocab_size
        self.k1 = k1
        self.b = b
        self.avg_dl = 400

    @staticmethod
    def tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]

    def encode(self, text: str) -> SparseVector:
        tokens = self.tokenize(text)
        if not tokens:
            return SparseVector(indices=[0], values=[0.001])

        tf = Counter(tokens)
        doc_len = len(tokens)
        indices: list[int] = []
        values: list[float] = []

        # Qdrant requires unique sparse indices — merge hash collisions.
        merged: dict[int, float] = {}
        for token, count in tf.items():
            idx = abs(hash(token)) % self.vocab_size
            tf_score = (count * (self.k1 + 1)) / (
                count + self.k1 * (1 - self.b + self.b * doc_len / self.avg_dl)
            )
            merged[idx] = merged.get(idx, 0.0) + float(tf_score)

        indices = list(merged.keys())
        values = list(merged.values())
        return SparseVector(indices=indices, values=values)
