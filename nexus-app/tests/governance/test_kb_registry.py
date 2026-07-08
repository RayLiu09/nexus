"""Tests for KbRegistry — KB-per-knowledge-type lazy and eager modes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus_app.config import Settings
from nexus_app.index.kb_registry import KbRegistry
from nexus_app.index.ragflow_adapter import FakeRAGFlowAdapter
from nexus_app.knowledge import config_loader as cl


@pytest.fixture
def fake_settings(tmp_path: Path) -> Settings:
    return Settings(
        ragflow_endpoint=None,
        ragflow_api_key=None,
        ragflow_kb_name_prefix="nexus-test",
        ragflow_kb_eager_preload=False,
        ragflow_embedding_model="BAAI/bge-large-zh-v1.5@BAAI",
    )


@pytest.fixture
def fake_adapter() -> FakeRAGFlowAdapter:
    return FakeRAGFlowAdapter()


@pytest.fixture
def isolated_rules(tmp_path: Path):
    """Patch config_loader to read a small fixture rules file."""
    rules = {
        "schema_version": "1.0",
        "classifications": [{"code": "D4", "name": "x", "description": "d", "criteria": ["c"]}],
        "levels": [{"code": "L1", "name": "x", "description": "d", "criteria": ["c"]}],
        "tags": [],
        "quality_scoring": {
            "dimensions": [{"name": "completeness", "weight": 1.0, "description": "d",
                            "check_items": [{"name": "has_title", "description": "d",
                                             "severity": "blocking"}]}],
            "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.8,
        },
        "knowledge_types": [
            {
                "code": "course_textbook",
                "name": "课程资源教材",
                "description": "d",
                "applicable_classifications": ["D4"],
                "default_level": "L1",
                "source_kind": "extracted_from_normalized",
                "chunking_mode": "passthrough_to_ragflow",
                "rag_pipeline": "pipeline_1",
                "source_criteria": ["x"],
                "chunking_strategy": "semantic",
                "chunking_config": {},
                "ragflow": {
                    "chunk_method": "book",
                    "parser_config": {"chunk_token_num": 512, "delimiter": "\n"},
                },
                "chunk_type": "semantic",
                "co_emission_rules": [],
                "implementation_tier": "A",
            },
            {
                "code": "qa_corpus",
                "name": "教学问答语料库",
                "description": "d",
                "applicable_classifications": ["D4"],
                "default_level": "L2",
                "source_kind": "extracted_from_normalized",
                "chunking_mode": "nexus_extract",
                "rag_pipeline": "pipeline_2",
                "source_criteria": ["x"],
                "chunking_strategy": "qa_extract",
                "chunking_config": {},
                "ragflow": {"chunk_method": "qa", "parser_config": {"chunk_token_num": 256}},
                "chunk_type": "qa_pair",
                "co_emission_rules": [],
                "implementation_tier": "B",
            },
        ],
    }
    fixture_path = tmp_path / "governance_rules.json"
    fixture_path.write_text(json.dumps(rules), encoding="utf-8")
    cl._load_all.cache_clear()
    with patch.object(cl, "_CONFIG_PATH", fixture_path):
        yield fixture_path
    cl._load_all.cache_clear()


class TestLazyEnsureKb:
    def test_first_call_creates_kb(self, fake_adapter, fake_settings, isolated_rules):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        kb_id = registry.ensure_kb("course_textbook")
        assert kb_id.startswith("fake_kb_")
        assert registry.get_cached("course_textbook") == kb_id
        assert registry.kb_name_for("course_textbook") == "nexus-test-course_textbook"

    def test_second_call_reuses_cache(self, fake_adapter, fake_settings, isolated_rules):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        kb_id_a = registry.ensure_kb("course_textbook")
        kb_id_b = registry.ensure_kb("course_textbook")
        assert kb_id_a == kb_id_b
        assert len(fake_adapter._datasets) == 1

    def test_existing_dataset_is_reused(self, fake_adapter, fake_settings, isolated_rules):
        existing = fake_adapter.create_dataset(
            name="nexus-test-course_textbook", chunk_method="book"
        )
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        kb_id = registry.ensure_kb("course_textbook")
        assert kb_id == existing["id"]
        assert len(fake_adapter._datasets) == 1


class TestEagerPreload:
    def test_preload_creates_all_kbs(self, fake_adapter, fake_settings, isolated_rules):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        result = registry.preload_all()
        assert set(result.keys()) == {"course_textbook", "qa_corpus"}
        assert len(fake_adapter._datasets) == 2

    def test_preload_idempotent(self, fake_adapter, fake_settings, isolated_rules):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        first = registry.preload_all()
        second = registry.preload_all()
        assert first == second
        assert len(fake_adapter._datasets) == 2


class TestKbNamingConvention:
    def test_chunk_method_matches_rules(self, fake_adapter, fake_settings, isolated_rules):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        registry.ensure_kb("course_textbook")
        registry.ensure_kb("qa_corpus")
        names_to_methods = {
            ds["name"]: ds["chunk_method"] for ds in fake_adapter._datasets.values()
        }
        assert names_to_methods["nexus-test-course_textbook"] == "book"
        assert names_to_methods["nexus-test-qa_corpus"] == "qa"

    def test_description_carries_chinese_name(
        self, fake_adapter, fake_settings, isolated_rules
    ):
        registry = KbRegistry(adapter=fake_adapter, settings=fake_settings)
        registry.ensure_kb("course_textbook")
        ds = next(iter(fake_adapter._datasets.values()))
        assert ds["description"] == "课程资源教材"
