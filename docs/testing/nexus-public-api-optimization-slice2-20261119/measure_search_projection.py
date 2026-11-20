"""Isolated ASGI measurement; no network, production data, workers or lifespan.

Run from the repo root with nexus-api/.venv/bin/python <this-file>.
Uses existing pytest seed/fixture factories to keep the permission/audit chain real.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "nexus-app"))
sys.path.insert(0, str(ROOT / "nexus-api"))
sys.path.insert(0, str(ROOT / "nexus-api/tests"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import conftest
from test_search_qa_audit import (
    _search_settings, _seed_caller, _seed_pgvector_search_chain, _StaticEmbeddingClient,
)
from nexus_api.api import open as open_api
from nexus_app import models
from nexus_app.index.collection_resolver import build_vector_metadata, resolve_collection
from nexus_app.index.pgvector_search import PgvectorSearchAdapter
from nexus_app.index.projection_maintenance import compact_batch


def percentile(values, fraction):
    return round(sorted(values)[math.ceil(len(values) * fraction) - 1], 3)


def measure():
    result = {
        "environment": "local FastAPI ASGI TestClient + isolated in-memory SQLite; static 3D embeddings",
        "limitations": "Not deployed or production latency; no network, PostgreSQL ANN, embedding calls, lifespan or workers. Uncompressed HTTP JSON body bytes.",
        "shape": {"chunks": 3, "image_uris_per_ref": 423, "answer_max_chars": 2000,
                  "repeats_per_view_per_scenario": 20, "warmups_per_view_per_scenario": 2},
        "scenarios": {},
    }
    with pytest.MonkeyPatch.context() as patch:
        sessions = conftest.session.__wrapped__(patch)
        session = next(sessions)
        try:
            _seed_pgvector_search_chain(session, n=3)
            caller = _seed_caller(session)
            app = conftest.app.__wrapped__(session, conftest.stub_user.__wrapped__(), caller)
            adapter = PgvectorSearchAdapter(
                settings=_search_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]),
            )
            patch.setattr(open_api, "get_pgvector_search_adapter", lambda: adapter)
            ref = session.get(models.NormalizedAssetRef, "search_ref")
            ref.lineage = {"raw_object_id": "search_raw", "image_uris": [
                f"s3://bucket/parsed/version/artifact/images/{i}-{'x' * 150}.png"
                for i in range(423)
            ]}
            for index in range(1, 4):
                chunk = session.get(models.KnowledgeChunk, f"search_chunk_{index}")
                resolution = resolve_collection(ref, chunk, embedding_model_alias="bge-m3:latest", embedding_dimension=3)
                row = session.get(models.KnowledgeEmbeddingPgvector, f"search_embedding_{index}")
                row.vector_metadata = build_vector_metadata(ref, chunk, resolution,
                    asset_id="search_asset", asset_version_id="search_version")
            session.commit()
            compact_batch(session, apply=True)
            session.commit()
            # No lifespan: measurement must not seed prompts or start background jobs.
            client = TestClient(app)
            queries = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                queries.append(statement)

            event.listen(session.bind, "before_cursor_execute", capture)
            try:
                for label, repetitions in (("untruncated_content", 50), ("long_content", 300)):
                    for index in range(1, 4):
                        session.get(models.KnowledgeChunk, f"search_chunk_{index}").content = (
                            f"课程{index}的操作流程与注意事项。" * repetitions
                        )
                    session.commit()
                    samples = {view: [] for view in ("full", "answer")}
                    bodies = {}
                    lineage_reads = {}
                    for iteration in range(22):
                        for view in ("full", "answer"):
                            session.expire_all()
                            queries.clear()
                            started = perf_counter()
                            response = client.get("/open/v1/search", params={
                                "q": "课程", "kb": "textbook_kb", "top_k": 3,
                                "response_view": view,
                            }, headers={"X-Trace-ID": f"slice2-{label}-{view}-{iteration:02d}"})
                            elapsed = (perf_counter() - started) * 1000
                            assert response.status_code == 200, response.text
                            if iteration >= 2:
                                samples[view].append(elapsed)
                            bodies[view] = response
                            lineage_reads[view] = any("normalized_asset_ref.lineage" in sql for sql in queries)
                    full = bodies["full"].json()["data"]["results"]
                    answer = bodies["answer"].json()["data"]["results"]
                    for before, after in zip(full, answer, strict=True):
                        for key in ("nexus_chunk_id", "normalized_ref_id", "score", "knowledge_type_code"):
                            assert before[key] == after[key]
                        assert after["content"] == before["content"][:2000]
                        assert after["content_chars"] == len(before["content"])
                    assert not lineage_reads["answer"]
                    output = {view: {
                        "http_body_bytes": len(bodies[view].content),
                        "local_p50_ms": round(statistics.median(samples[view]), 3),
                        "local_p95_ms": percentile(samples[view], .95),
                        "reads_normalized_lineage": lineage_reads[view],
                        "elapsed_ms_samples": [round(n, 3) for n in samples[view]],
                    } for view in samples}
                    output["body_reduction_pct"] = round(100 * (1 - len(bodies["answer"].content) / len(bodies["full"].content)), 3)
                    output["content_chars_per_hit"] = [x["content_chars"] for x in answer]
                    output["content_truncated_per_hit"] = [x["content_truncated"] for x in answer]
                    output["same_ids_scores_and_content_prefix"] = True
                    result["scenarios"][label] = output
            finally:
                event.remove(session.bind, "before_cursor_execute", capture)
                client.close()
        finally:
            sessions.close()
    return result


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    data = measure()
    output = Path(__file__).with_name("projection-measurement.json")
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))
