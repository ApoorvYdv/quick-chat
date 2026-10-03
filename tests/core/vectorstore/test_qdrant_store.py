from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from quick_chat_api.core.vectorstore.base import VectorFilter, VectorPoint
from quick_chat_api.core.vectorstore.providers.qdrant import QdrantVectorStore


def _make_store() -> tuple[QdrantVectorStore, MagicMock]:
    with patch("qdrant_client.QdrantClient") as client_cls:
        client = MagicMock()
        client_cls.return_value = client
        store = QdrantVectorStore(
            url="http://localhost:6333",
            collection_prefix="test_collection",
            vector_size=8,
        )
    return store, client


def test_collection_created_lazily_on_first_use_when_missing():
    store, client = _make_store()
    client.collection_exists.return_value = False

    store.upsert_points("acme", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})])

    client.create_collection.assert_called_once()
    _, kwargs = client.create_collection.call_args
    assert kwargs["collection_name"] == "test_collection__acme"
    assert client.create_payload_index.call_count > 0


def test_collection_creation_skipped_when_already_present():
    store, client = _make_store()
    client.collection_exists.return_value = True

    store.upsert_points("acme", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})])

    client.create_collection.assert_not_called()


def test_collection_ensured_only_once_per_agency():
    store, client = _make_store()
    client.collection_exists.return_value = False

    store.upsert_points("acme", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})])
    store.upsert_points("acme", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})])

    client.create_collection.assert_called_once()


def test_different_agencies_map_to_different_collections():
    store, client = _make_store()
    client.collection_exists.return_value = True

    store.upsert_points("acme", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})])
    store.upsert_points(
        "globex", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})]
    )

    collections = {c.kwargs["collection_name"] for c in client.upsert.call_args_list}
    assert collections == {"test_collection__acme", "test_collection__globex"}


def test_agency_name_is_sanitized_for_collection_name():
    store, client = _make_store()
    client.collection_exists.return_value = True

    store.upsert_points(
        "Acme PD!", [VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={})]
    )

    assert (
        client.upsert.call_args.kwargs["collection_name"] == "test_collection__acme_pd"
    )


def test_upsert_points_batches_in_one_call():
    store, client = _make_store()
    client.collection_exists.return_value = True
    points = [
        VectorPoint(id=uuid4(), vector=[0.1] * 8, payload={"case_record_id": "x"}),
        VectorPoint(id=uuid4(), vector=[0.2] * 8, payload={"case_record_id": "x"}),
    ]
    store.upsert_points("acme", points)
    client.upsert.assert_called_once()
    _, kwargs = client.upsert.call_args
    assert len(kwargs["points"]) == 2


def test_upsert_points_skips_empty_list_without_touching_collection():
    store, client = _make_store()
    store.upsert_points("acme", [])
    client.upsert.assert_not_called()
    client.collection_exists.assert_not_called()


def test_search_scopes_to_the_agencys_collection():
    store, client = _make_store()
    client.collection_exists.return_value = True
    hit = MagicMock(id=str(uuid4()), score=0.9, payload={"source_type": "case"})
    client.query_points.return_value = MagicMock(points=[hit])

    results = store.search(
        "acme", query_vector=[0.1] * 8, filter_=VectorFilter(), top_k=5
    )

    assert len(results) == 1
    assert results[0].score == 0.9
    _, kwargs = client.query_points.call_args
    assert kwargs["collection_name"] == "test_collection__acme"
    assert kwargs["limit"] == 5


def test_search_applies_optional_case_and_source_type_filters():
    store, client = _make_store()
    client.collection_exists.return_value = True
    client.query_points.return_value = MagicMock(points=[])
    case_id = uuid4()

    store.search(
        "acme",
        query_vector=[0.1] * 8,
        filter_=VectorFilter(case_record_id=case_id, source_types=["case", "charge"]),
        top_k=10,
    )

    conditions = client.query_points.call_args.kwargs["query_filter"].must
    keys = {c.key for c in conditions}
    assert keys == {"case_record_id", "source_type"}


def test_delete_by_filter_scopes_to_the_agencys_collection():
    store, client = _make_store()
    client.collection_exists.return_value = True
    store.delete_by_filter("acme", VectorFilter())
    client.delete.assert_called_once()
    _, kwargs = client.delete.call_args
    assert kwargs["collection_name"] == "test_collection__acme"


def test_delete_points_skips_empty_list_without_touching_collection():
    store, client = _make_store()
    store.delete_points("acme", [])
    client.delete.assert_not_called()
    client.collection_exists.assert_not_called()


def test_list_points_pages_through_scroll_until_offset_is_none():
    store, client = _make_store()
    client.collection_exists.return_value = True
    first, second = uuid4(), uuid4()
    client.scroll.side_effect = [
        ([MagicMock(id=str(first), payload={"a": 1})], "next-page"),
        ([MagicMock(id=str(second), payload=None)], None),
    ]

    points = store.list_points("acme", VectorFilter(case_record_id=uuid4()))

    assert [p.id for p in points] == [first, second]
    assert points[1].payload == {}
    assert client.scroll.call_count == 2
    assert client.scroll.call_args_list[0].kwargs["with_vectors"] is False
