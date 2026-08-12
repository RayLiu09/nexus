"""Vision recovery for flattened talent-training-plan capability tables."""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from nexus_app.pipeline.mineru_converter import (
    _detect_ttp_structure_loss,
    _parse_ttp_structure_recovery,
    convert,
)


_HTML = (
    "<table><tr><td>职业岗位（群）</td><td>岗位核心能力</td><td>学习领域</td></tr>"
    "<tr><td>跨境电商B2C运营岗</td><td>跨境电商产品挖掘能力跨境电商平台操作能力网店运营分析能力</td>"
    "<td>跨境电子商务实务网络营销</td></tr></table>"
)


def _table_block(image_path: str = "ttp.jpg") -> dict:
    return {
        "type": "table",
        "bbox": [20, 30, 600, 500],
        "blocks": [
            {"type": "table_caption", "lines": [{"spans": [{"type": "text", "content": "表2 职业岗位核心能力"}]}]},
            {"type": "table_body", "lines": [{"spans": [{"type": "table", "html": _HTML, "image_path": image_path}]}]},
        ],
    }


class _Storage:
    def get_bytes(self, _key: str) -> bytes:
        image = Image.new("RGB", (80, 80), "white")
        output = BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()


class _Analyzer:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def analyze(self, _image: bytes, block_type: str, caption: str) -> str:
        self.calls.append((block_type, caption))
        return self.response


def _valid_response() -> str:
    return (
        '{"rows":[{"row_index":1,"position_name":"跨境电商B2C运营岗",'
        '"skills":["跨境电商产品挖掘能力","跨境电商平台操作能力","网店运营分析能力"],'
        '"learning_domains":["跨境电子商务实务","网络营销"]}]}'
    )


def test_detection_is_narrow_and_requires_missing_boundaries():
    detection = _detect_ttp_structure_loss(_HTML)
    assert detection is not None
    assert detection["affected_row_indexes"] == [1]
    assert _detect_ttp_structure_loss(_HTML.replace("网店运营分析能力", "网店运营分析能力<br>")) is None
    assert _detect_ttp_structure_loss("<table><tr><td>项目</td><td>内容</td></tr><tr><td>A</td><td>能力能力能力</td></tr></table>") is None


def test_convert_persists_only_validated_vision_recovery():
    analyzer = _Analyzer(_valid_response())
    blocks, _markdown, _toc = convert(
        [{"page_idx": 3, "para_blocks": [_table_block()]}],
        image_uris={"ttp.jpg": "s3://bucket/parsed/ttp.jpg"}, image_analyzer=analyzer, storage=_Storage(),
    )
    assert analyzer.calls[0][0] == "talent_training_plan_table_structure"
    recovery = blocks[0]["table_structure_recovery"]
    assert recovery["status"] == "recovered"
    assert recovery["source"] == "litellm_default_governance_model"
    assert recovery["recovered_rows"][0]["skills"][1] == {"text": "跨境电商平台操作能力", "segment_index": 2}
    assert "raw response" not in recovery


def test_convert_resolves_basename_only_image_path_when_unambiguous():
    analyzer = _Analyzer(_valid_response())
    blocks, _markdown, _toc = convert(
        [{"page_idx": 3, "para_blocks": [_table_block("ttp.jpg")]}],
        image_uris={"source/images/ttp.jpg": "s3://bucket/parsed/ttp.jpg"}, image_analyzer=analyzer, storage=_Storage(),
    )
    assert analyzer.calls[0][0] == "talent_training_plan_table_structure"
    assert blocks[0]["table_structure_recovery"]["status"] == "recovered"


def test_recovery_rejects_any_non_json_only_or_unbound_response():
    detection = _detect_ttp_structure_loss(_HTML)
    assert detection is not None
    assert _parse_ttp_structure_recovery("说明：" + _valid_response(), detection) is None
    assert _parse_ttp_structure_recovery(_valid_response() + "\n", detection) is None
    assert _parse_ttp_structure_recovery(_valid_response().replace("跨境电商B2C运营岗", "错误岗位"), detection) is None


def test_recovery_rejects_missing_required_source_row():
    html = _HTML.replace(
        "</tr></table>",
        "</tr><tr><td>跨境电商客服岗</td><td>客户服务沟通能力客户投诉处理能力客户关系维护能力</td><td>客服实务</td></tr></table>",
    )
    detection = _detect_ttp_structure_loss(html)
    assert detection is not None
    recovered = _parse_ttp_structure_recovery(_valid_response(), detection)
    assert recovered is None


def test_convert_does_not_inject_source_rows_into_the_vision_prompt():
    analyzer = _Analyzer(_valid_response())
    blocks, _markdown, _toc = convert(
        [{"page_idx": 3, "para_blocks": [_table_block()]}],
        image_uris={"ttp.jpg": "s3://bucket/parsed/ttp.jpg"}, image_analyzer=analyzer, storage=_Storage(),
    )
    assert blocks[0]["table_structure_recovery"]["status"] == "recovered"
    assert analyzer.calls[0][1] == "表2 职业岗位核心能力"


def test_convert_marks_failed_recovery_and_keeps_normalized_source_table():
    analyzer = _Analyzer("```json\n" + _valid_response() + "\n```")
    blocks, _markdown, _toc = convert(
        [{"page_idx": 3, "para_blocks": [_table_block()]}],
        image_uris={"ttp.jpg": "s3://bucket/parsed/ttp.jpg"}, image_analyzer=analyzer, storage=_Storage(),
    )
    recovery = blocks[0]["table_structure_recovery"]
    assert recovery["status"] == "failed"
    assert recovery["reason"] == "incomplete_page_slice_recovery"
    assert blocks[0]["table_html"] == _HTML


def test_cross_page_recovery_combines_anchor_and_continuation_rows():
    html = _HTML.replace(
        "</tr></table>",
        "</tr><tr><td>跨境电商客服岗</td><td>客户服务沟通能力客户投诉处理能力客户关系维护能力</td><td>客服实务客户关系管理</td></tr></table>",
    )
    anchor = _table_block()
    anchor["blocks"][1]["lines"][0]["spans"][0]["html"] = html
    continuation = {"type": "table", "bbox": [20, 30, 600, 500], "blocks": []}
    class _SliceAnalyzer:
        def __init__(self):
            self.calls = []
        def analyze(self, _image, block_type, caption):
            self.calls.append((block_type, caption))
            if block_type == "table":
                return None
            assert block_type == "talent_training_plan_table_structure"
            return ('{"rows":[{"row_index":1,"position_name":"跨境电商B2C运营岗",'
                '"skills":["跨境电商产品挖掘能力","跨境电商平台操作能力","网店运营分析能力"],'
                '"learning_domains":["跨境电子商务实务","网络营销"]},'
                '{"row_index":2,"position_name":"跨境电商客服岗",'
                '"skills":["客户服务沟通能力","客户投诉处理能力","客户关系维护能力"],'
                '"learning_domains":["客服实务","客户关系管理"]}]}')
    analyzer = _SliceAnalyzer()
    def render(page, bbox=None):
        assert page == 4 and bbox == [20, 30, 600, 500]
        return _Storage().get_bytes("continuation.jpg")
    blocks, _markdown, _toc = convert(
        [{"page_idx": 3, "para_blocks": [anchor]}, {"page_idx": 4, "para_blocks": [continuation]}],
        image_uris={"ttp.jpg": "s3://bucket/parsed/ttp.jpg"}, image_analyzer=analyzer, storage=_Storage(), pdf_renderer=render,
    )
    recovery = blocks[0]["table_structure_recovery"]
    assert recovery["status"] == "recovered"
    assert [row["row_index"] for row in recovery["recovered_rows"]] == [1, 2]
    assert [call for call in analyzer.calls if call[0] == "talent_training_plan_table_structure"] == [
        ("talent_training_plan_table_structure", "表2 职业岗位核心能力")
    ]
