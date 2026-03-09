"""Tests for EmbeddingEngine — sentence-transformers embeddings and similarity."""

import numpy as np
import pytest

pytestmark = pytest.mark.slow


class TestEmbed:
    def test_embed_returns_ndarray(self, embedding_engine):
        result = embedding_engine.embed("hello world")
        assert isinstance(result, np.ndarray)

    def test_embed_dimension(self, embedding_engine):
        result = embedding_engine.embed("hello world")
        assert result.shape == (384,)

    def test_embed_normalized(self, embedding_engine):
        result = embedding_engine.embed("hello world")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 0.01

    def test_embed_batch_shape(self, embedding_engine):
        result = embedding_engine.embed_batch(["a", "b", "c"])
        assert result.shape == (3, 384)


class TestSimilarity:
    def test_identical_vectors_similarity_one(self, embedding_engine):
        v = embedding_engine.embed("python programming")
        sim = embedding_engine.cosine_similarity(v, v)
        assert abs(sim - 1.0) < 0.001

    def test_related_higher_than_unrelated(self, embedding_engine):
        py = embedding_engine.embed("python programming language")
        code = embedding_engine.embed("coding in python software")
        cook = embedding_engine.embed("baking chocolate cookies recipe")

        sim_related = embedding_engine.cosine_similarity(py, code)
        sim_unrelated = embedding_engine.cosine_similarity(py, cook)
        assert sim_related > sim_unrelated

    def test_similarity_matrix_shape(self, embedding_engine):
        a = embedding_engine.embed_batch(["x", "y"])
        b = embedding_engine.embed_batch(["a", "b", "c"])
        mat = embedding_engine.cosine_similarity_matrix(a, b)
        assert mat.shape == (2, 3)
