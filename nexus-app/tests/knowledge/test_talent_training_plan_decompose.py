from types import SimpleNamespace

from nexus_app.enums import ChunkType, ChunkingStrategy
from nexus_app.knowledge.chunking_strategies.talent_training_plan_decompose import (
    TalentTrainingPlanDecomposeStrategy,
)


def _config(**overrides):
    values = {
        "chunking_config": {
            "include_semantic_units": [
                "training_goal", "training_specification", "position_capability", "course", "supplementary_section",
            ],
            "narrative_chunk_size": 300,
            "narrative_chunk_overlap": 24,
            "course_content_chunk_size": 80,
            "course_content_overlap": 12,
            "supplementary_headings": ["入学要求", "实施保障"],
        },
        "chunking_strategy": "talent_training_plan_decompose",
        "source_kind": "extracted_from_normalized",
        "max_chunks_per_unit": 100,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _block(block_id, text, block_type="paragraph", page=1):
    return {"block_id": block_id, "text": text, "block_type": block_type, "page": page, "bbox": [0, 0, 10, 10]}


def _emission():
    return {
        "code": "talent_training_dataset",
        "talent_training_plan": {
            "schema_version": "talent_training_plan.v1",
            "institution_name": "测试职业学院",
            "major_name": "跨境电子商务",
            "major_code": "530702",
            "education_level": "高职",
            "study_duration": "三年",
            "training_goal": "培养具备跨境店铺运营与海外营销能力的高素质技术技能人才。",
            "training_specification": {
                "abilities": [{"name": "具备跨境平台运营能力", "evidence": {"block_ids": ["b-goal"]}}],
                "knowledge_requirements": [{"name": "掌握国际贸易与物流知识", "evidence": {"block_ids": ["b-spec"]}}],
                "qualities": [],
            },
            "career_orientation": {
                "positions": [
                    {"name": "跨境电商运营岗", "skills": [{"name": "选品能力", "evidence": {"block_ids": ["b-position"]}}], "learning_domains": [{"name": "跨境电商运营", "evidence": {"block_ids": ["b-position"]}}], "evidence": {"block_ids": ["b-position"]}},
                    {"name": "无证据岗位", "skills": [], "learning_domains": [], "evidence": {"block_ids": ["b-position"]}},
                ],
            },
            "courses": [
                {"course_name": "跨境电商运营", "curriculum_group": "专业核心课", "course_type": "course", "course_objective": "能完成店铺运营与数据分析。", "course_content": "学习选品、商品发布、广告投放、店铺诊断和数据复盘。", "skill_refs": [{"name": "选品能力"}], "evidence": {"block_ids": ["b-course"]}},
                {"course_name": "1", "course_content": "无效课程", "evidence": {"block_ids": ["b-course"]}},
            ],
        },
    }


def test_projects_only_rag_supplement_units_with_evidence_locators():
    blocks = [
        _block("b-goal", "培养目标", "heading"), _block("b-spec", "培养规格", "heading"),
        _block("b-position", "岗位能力表", "table"), _block("b-course", "课程体系", "table"),
        _block("b-admission", "入学要求", "heading"), _block("b-admission-text", "具有高中阶段教育或同等学力。"),
        _block("b-assurance", "实施保障", "heading"), _block("b-assurance-text", "配备校内外实训基地。"),
    ]
    chunks = TalentTrainingPlanDecomposeStrategy(_config().chunking_config).chunk(
        "", _emission(), _config(), "ref-1", content_blocks=blocks
    )

    units = [chunk.chunk_metadata["semantic_unit"] for chunk in chunks]
    assert units.count("training_goal") == 1
    assert units.count("training_specification") == 2
    assert units.count("position_capability") == 1
    assert units.count("course") == 1
    assert units.count("supplementary_section") == 2
    assert all(chunk.chunk_type == ChunkType.SEMANTIC_BLOCK for chunk in chunks)
    assert all(chunk.chunking_strategy == ChunkingStrategy.TALENT_TRAINING_PLAN_DECOMPOSE for chunk in chunks)
    assert all(chunk.source_block_ids for chunk in chunks)
    assert not any("无证据岗位" in chunk.content for chunk in chunks)
    course = next(chunk for chunk in chunks if chunk.chunk_metadata["semantic_unit"] == "course")
    assert "课程目标：能完成店铺运营与数据分析" in course.content
    assert "课程内容" in course.content
    assert course.chunk_metadata["course_name"] == "跨境电商运营"


def test_does_not_emit_structured_identity_or_certificate_units():
    config = _config()
    chunks = TalentTrainingPlanDecomposeStrategy(config.chunking_config).chunk(
        "", _emission(), config, "ref-1", content_blocks=[_block("b-course", "课程体系", "table")]
    )
    units = {chunk.chunk_metadata["semantic_unit"] for chunk in chunks}
    assert "plan_profile" not in units
    assert "certificate" not in units


def test_long_course_content_is_bounded_and_repeats_course_context():
    emission = _emission()
    emission["talent_training_plan"]["courses"][0]["course_content"] = "。".join(["学习跨境电商运营的完整工作过程"] * 12) + "。"
    config = _config()
    chunks = TalentTrainingPlanDecomposeStrategy(config.chunking_config).chunk(
        "", emission, config, "ref-1", content_blocks=[_block("b-course", "课程体系", "table")]
    )
    courses = [chunk for chunk in chunks if chunk.chunk_metadata["semantic_unit"] == "course"]
    assert len(courses) > 1
    assert all("课程：跨境电商运营" in chunk.content for chunk in courses)
    assert {chunk.chunk_metadata["course_content_parts"] for chunk in courses} == {len(courses)}


def test_long_training_specification_is_split_on_semantic_boundaries():
    emission = _emission()
    emission["talent_training_plan"]["training_specification"]["abilities"] = [
        {"name": f"具备跨境电商运营能力第{index}项，能够完成选品、商品发布、广告投放、店铺诊断与数据复盘工作。"}
        for index in range(12)
    ]
    config = _config()
    chunks = TalentTrainingPlanDecomposeStrategy(config.chunking_config).chunk(
        "", emission, config, "ref-1", content_blocks=[_block("b-spec", "培养规格", "heading")]
    )
    abilities = [chunk for chunk in chunks if chunk.chunk_metadata.get("specification_category") == "abilities"]
    assert len(abilities) > 1
    assert all(len(chunk.content) <= 360 for chunk in abilities)
    assert {chunk.chunk_metadata["semantic_parts"] for chunk in abilities} == {len(abilities)}
