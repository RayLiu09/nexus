from __future__ import annotations

from nexus_app.enums import ChunkType
from nexus_app.knowledge.config_loader import get_knowledge_type_config, reload_config
from nexus_app.knowledge.services import run_knowledge_pipeline


def test_course_textbook_textbook_kb_builds_semantic_chunks_with_locator():
    reload_config()
    content = "\n".join([
        "# 项目一 短视频认知",
        "## 任务一 认识短视频",
        "本任务介绍短视频平台、账号定位和内容形态。",
        "## 课后训练",
        "请分析一个短视频账号的定位与内容特点。",
    ])
    blocks = [
        {
            "block_id": "b1",
            "block_type": "heading",
            "seq_no": 1,
            "page": 1,
            "bbox": [0, 0, 100, 20],
            "text": "项目一 短视频认知",
            "heading_level": 1,
            "md_char_range": [0, 12],
        },
        {
            "block_id": "b2",
            "block_type": "heading",
            "seq_no": 2,
            "page": 1,
            "bbox": [0, 25, 100, 45],
            "text": "任务一 认识短视频",
            "heading_level": 2,
            "md_char_range": [13, 26],
        },
        {
            "block_id": "b3",
            "block_type": "paragraph",
            "seq_no": 3,
            "page": 1,
            "bbox": [0, 50, 500, 90],
            "text": "本任务介绍短视频平台、账号定位和内容形态。",
            "content": "本任务介绍短视频平台、账号定位和内容形态。",
            "md_char_range": [27, 49],
        },
        {
            "block_id": "b4",
            "block_type": "heading",
            "seq_no": 4,
            "page": 2,
            "bbox": [0, 0, 100, 20],
            "text": "课后训练",
            "heading_level": 2,
            "md_char_range": [50, 57],
        },
        {
            "block_id": "b5",
            "block_type": "paragraph",
            "seq_no": 5,
            "page": 2,
            "bbox": [0, 25, 500, 70],
            "text": "请分析一个短视频账号的定位与内容特点。",
            "content": "请分析一个短视频账号的定位与内容特点。",
            "md_char_range": [58, len(content)],
        },
    ]

    kt_config = get_knowledge_type_config("textbook_kb")
    assert kt_config.chunking_mode == "nexus_semantic"
    assert kt_config.chunking_strategy == "semantic_repack"
    assert "course_textbook" in kt_config.raw["applicable_classifications"]

    chunks = run_knowledge_pipeline(
        content,
        [{"code": "textbook_kb", "primary": True, "co_emission_origin": None}],
        "ref-course-textbook",
        content_blocks=blocks,
    )

    assert chunks
    assert all(chunk.knowledge_type_code == "textbook_kb" for chunk in chunks)
    assert all(chunk.chunk_type == ChunkType.SEMANTIC_BLOCK for chunk in chunks)
    assert all(chunk.content.strip() for chunk in chunks)
    assert all(chunk.source_block_ids for chunk in chunks)
    assert all(chunk.locator for chunk in chunks)
    assert any(
        heading["title"] == "项目一 短视频认知"
        for chunk in chunks
        for heading in chunk.locator["heading_path"]
    )
