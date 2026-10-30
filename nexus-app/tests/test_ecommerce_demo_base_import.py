import json
from pathlib import Path

from scripts.import_ecommerce_demo_bases import _national_rows, _provincial_rows


ROOT = Path(__file__).resolve().parents[2]


def test_complete_demo_base_samples_parse_to_expected_counts():
    national = _national_rows(
        json.loads((ROOT / "docs/samples/国家电子商务示范基地.json").read_text())
    )
    provincial, metadata = _provincial_rows(
        json.loads((ROOT / "docs/samples/省级电子商务示范基地.json").read_text())
    )

    assert len(national) == 170
    assert len({row["source_path"] for row in national}) == 170
    assert {row["batch_code"] for row in national} == {"first", "second", "supplement"}
    assert len(provincial) == 142
    assert len({row["source_path"] for row in provincial}) == 142
    assert metadata == {
        "source_declared_total": 142,
        "source_declared_pages": 10,
        "source_current_page": 1,
        "source_page_size": 20,
    }
