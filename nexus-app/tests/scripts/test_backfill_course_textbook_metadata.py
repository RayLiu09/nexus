from scripts.backfill_course_textbook_metadata import merge_bibliographic_metadata


def test_merge_fills_only_missing_bibliographic_fields() -> None:
    merged, changed = merge_bibliographic_metadata(
        {"publisher": "已有出版社", "chief_editors": [], "source_block_ids": ["old"]},
        {
            "publisher": "新出版社",
            "chief_editors": ["张三", "李四"],
            "publish_date": "2024-08",
            "source_block_ids": ["new"],
        },
    )

    assert merged["publisher"] == "已有出版社"
    assert merged["chief_editors"] == ["张三", "李四"]
    assert merged["publish_date"] == "2024-08"
    assert merged["source_block_ids"] == ["new", "old"]
    assert changed == ["chief_editors", "publish_date"]


def test_merge_keeps_unpublished_material_empty() -> None:
    merged, changed = merge_bibliographic_metadata(
        {"title": "内部讲义"},
        {"publisher": None, "chief_editors": [], "publish_date": None},
    )

    assert merged == {"title": "内部讲义"}
    assert changed == []
