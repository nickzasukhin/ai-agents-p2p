"""Embedding Engine — vectorizes text using sentence-transformers for semantic matching."""

import structlog
import numpy as np
from functools import lru_cache

log = structlog.get_logger()

# Default model — small, fast, good for semantic similarity
DEFAULT_MODEL = "all-MiniLM-L6-v2"


class EmbeddingEngine:
    """Generates semantic embeddings for agent skills and needs.

    Uses sentence-transformers to create dense vector representations
    of text, enabling cosine similarity matching between agents.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            log.info("loading_embedding_model", model=self.model_name)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            log.info("embedding_model_loaded", model=self.model_name)
        return self._model

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding vector for a single text.

        Args:
            text: Input text to embed.

        Returns:
            Normalized embedding vector (384 dimensions for MiniLM).
        """
        model = self._get_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return np.array(embedding)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Generate embedding vectors for multiple texts.

        Args:
            texts: List of input texts to embed.

        Returns:
            Array of normalized embedding vectors, shape (n, dim).
        """
        if not texts:
            return np.array([])

        model = self._get_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        return np.array(embeddings)

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors.

        Since vectors are already normalized, this is just a dot product.
        """
        return float(np.dot(a, b))

    @staticmethod
    def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute pairwise cosine similarity between two sets of vectors.

        Args:
            a: Matrix of shape (n, dim)
            b: Matrix of shape (m, dim)

        Returns:
            Similarity matrix of shape (n, m)
        """
        return np.dot(a, b.T)
