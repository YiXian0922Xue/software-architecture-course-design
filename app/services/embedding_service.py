import hashlib
import math
import re

import httpx


class EmbeddingService:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider = "unknown"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
                response.raise_for_status()
                vectors = response.json().get("embeddings", [])
                if len(vectors) == len(texts):
                    self.provider = f"ollama:{self.model}"
                    return vectors
        except (httpx.HTTPError, ValueError):
            pass
        self.provider = "local-hash-fallback"
        return [self._hash_embedding(text) for text in texts]

    @staticmethod
    def _hash_embedding(text: str, dimensions: int = 256) -> list[float]:
        vector = [0.0] * dimensions
        lowered = text.lower()
        # Chinese has no whitespace boundaries. Character bi/tri-grams keep the
        # offline fallback useful instead of hashing an entire sentence as one token.
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        tokens = re.findall(r"[a-z0-9_]+", lowered)
        tokens += [chinese[i:i+n] for n in (2, 3) for i in range(max(0, len(chinese)-n+1))]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
