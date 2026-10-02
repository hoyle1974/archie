"""Embedders turn text into 384-d unit vectors (DESIGN §5.4).

`min_similarity` is the cosine below which a vector hit counts as noise, since a
nearest-neighbor search always returns *something*.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

DIM = 384


class Embedder(Protocol):
    name: str
    dim: int
    min_similarity: float

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...


def _thread_lock_for_tqdm() -> None:
    """sentence-transformers wraps encode() in tqdm, which builds a multiprocessing lock even
    with the bar off. That spawns multiprocessing's resource tracker, passing stderr's fd;
    inside the TUI, Textual has replaced stderr, so the spawn fails ("bad value(s) in
    fds_to_keep"). A plain thread lock avoids the subprocess entirely."""
    import threading

    from tqdm import tqdm

    tqdm.set_lock(threading.RLock())


class SentenceTransformerEmbedder:
    """Local model via sentence-transformers. bge models want a prefix on queries."""

    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, name: str = "BAAI/bge-small-en-v1.5", min_similarity: float = 0.5):
        self.name = name
        self.dim = DIM
        self.min_similarity = min_similarity
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            _thread_lock_for_tqdm()
            self._model = SentenceTransformer(self.name)
        return self._model

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        if query and "bge" in self.name:
            texts = [self.QUERY_PREFIX + t for t in texts]
        vecs = self._load().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return [v.tolist() for v in vecs]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder for tests: lexical, not semantic."""

    def __init__(self, name: str = "hash", min_similarity: float = 0.05):
        self.name = name
        self.dim = DIM
        self.min_similarity = min_similarity

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * DIM
            for tok in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


def make_embedder(config: dict) -> Embedder:
    name = config["index"]["embed_model"]
    return HashEmbedder() if name == "hash" else SentenceTransformerEmbedder(name)
