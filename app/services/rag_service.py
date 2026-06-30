import math

from app.repositories.sqlite_repository import SQLiteRepository
from app.services.embedding_service import EmbeddingService


class RAGService:
    def __init__(self, repository: SQLiteRepository, embeddings: EmbeddingService):
        self.repository = repository
        self.embeddings = embeddings

    @staticmethod
    def split(text: str, size: int = 700, overlap: int = 100) -> list[str]:
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not normalized:
            return []
        chunks, start = [], 0
        while start < len(normalized):
            end = min(start + size, len(normalized))
            if end < len(normalized):
                boundary = max(normalized.rfind("\n", start, end), normalized.rfind("。", start, end))
                if boundary > start + size // 2:
                    end = boundary + 1
            chunks.append(normalized[start:end])
            if end == len(normalized):
                break
            start = max(end - overlap, start + 1)
        return chunks

    async def index(self, project_id: str, resource_id: str, name: str, text: str):
        chunks = self.split(text)
        vectors = await self.embeddings.embed(chunks)
        self.repository.add_chunks((project_id, resource_id, name, chunk, vector) for chunk, vector in zip(chunks, vectors))

    async def search(self, project_id: str, query: str, limit: int = 6) -> list[dict]:
        rows = self.repository.get_chunks(project_id)
        if not rows:
            return []
        query_vector = (await self.embeddings.embed([query]))[0]
        # A project may have been indexed while Ollama was offline and queried
        # after it came back. Score both persisted fallback vectors (256d) and
        # current provider vectors instead of silently dropping old knowledge.
        query_vectors = {len(query_vector): query_vector}
        query_vectors.setdefault(256, EmbeddingService._hash_embedding(query))
        for row in rows:
            compatible = query_vectors.get(len(row["embedding"]))
            row["score"] = self._cosine(compatible, row["embedding"]) if compatible else -1.0
        return sorted(rows, key=lambda item: item["score"], reverse=True)[:limit]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0.0
        denominator = math.sqrt(sum(x*x for x in left)) * math.sqrt(sum(x*x for x in right))
        return sum(a*b for a, b in zip(left, right)) / denominator if denominator else 0.0
