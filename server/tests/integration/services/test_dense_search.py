"""Repository-filtered dense search on a table dominated by another repository.

An HNSW index returns the globally nearest rows and applies the SQL filter
afterwards. On a table where one repository owns most of the vectors, the
default candidate pool can be filled entirely by that repository, leaving the
one being asked about with too few -- or no -- hits. pgvector 0.8's iterative
scan is what keeps the walk going after the filter rejects a row.
"""

import math
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.models.embedding import Embedding
from app.services.rag import _vector_search
from tests.factories import make_repo, make_user

pytestmark = pytest.mark.integration


def _basis_vector(index: int = 0, dimensions: int = 1536) -> list[float]:
    """A unit vector along one axis."""
    vector = [0.0] * dimensions
    vector[index] = 1.0
    return vector


def _angled_vector(theta: float, dimensions: int = 1536) -> list[float]:
    """A unit vector a small angle away from the first axis."""
    return [math.cos(theta), math.sin(theta)] + [0.0] * (dimensions - 2)


async def test_a_dominant_repository_does_not_starve_a_filtered_search(db_session):
    """The target repository still fills its top-k when another holds 300 near-identical rows."""
    user = await make_user(db_session)
    noisy = await make_repo(db_session, user, name="noisy")
    target = await make_repo(db_session, user, name="target")

    query_vector = _basis_vector()

    # Distance 0: these occupy the global top of the index and are all filtered
    # out by ``repository_id`` afterwards.
    db_session.add_all(
        [
            Embedding(
                repository_id=noisy.id,
                source_id=uuid4(),
                source_type="symbol",
                chunk_text=f"noise {i}",
                embedding=query_vector,
            )
            for i in range(300)
        ]
    )

    # Distance ~0.02: comfortably inside the ``< 0.7`` cut, but behind every
    # row above in global ordering.
    db_session.add_all(
        [
            Embedding(
                repository_id=target.id,
                source_id=uuid4(),
                source_type="symbol",
                chunk_text=f"target {i}",
                embedding=_angled_vector(0.2),
            )
            for i in range(10)
        ]
    )
    await db_session.flush()

    # Force the index path. With a sequential scan the filter runs before the
    # distance cut and the test would pass without exercising HNSW at all.
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))

    hits = await _vector_search(db_session, target.id, query_vector, top_k=10)

    assert len(hits) == 10
    assert {hit.repository_id for hit in hits} == {target.id}
