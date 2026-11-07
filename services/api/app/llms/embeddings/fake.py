"""Deterministic offline embeddings for tests and development without vendor keys.

Hashed bag of words: lowercase words (with a light plural strip and a stop-word list) and word
bigrams are hashed into 1536 signed buckets and the vector is L2-normalised. Texts that share
words score high, unrelated texts near zero, so retrieval behaves sensibly offline. Its scores
run lower than a neural model's, so the drop threshold is lower too.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import math
import re

from app.llms.embeddings.base import DIMENSIONS, EmbeddingUnavailable

_WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its my of on or our "
    "the their them they this to was we what when where which who will with you your".split()
)


def _terms(text: str) -> list[str]:
    words = []
    for word in _WORD.findall(text.lower()):
        if word in STOP_WORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]


def embed_text(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for term in _terms(text):
        digest = hashlib.blake2b(term.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * (0.5 if "_" in term else 1.0)
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeEmbeddings:
    provider = "fake"
    model = "fake-hash-1536"
    dimensions = DIMENSIONS
    similarity_threshold = 0.12

    def __init__(self, *, latency_s: float = 0.0, fail_times: int = 0) -> None:
        self.latency_s = latency_s
        self.fail_times = fail_times
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmbeddingUnavailable("fake vendor outage")
        return [embed_text(t, self.dimensions) for t in texts]

    async def aclose(self) -> None:
        return None
