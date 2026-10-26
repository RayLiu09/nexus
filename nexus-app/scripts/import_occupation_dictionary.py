"""Build a reviewed seed or idempotently import it (dry-run by default)."""

import argparse
import json
from pathlib import Path

from nexus_app.database import get_engine
from nexus_app.reference_data.occupation_dictionary import (
    build_seed,
    import_catalog,
    load_seed,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--seed-output", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.pdf and not args.workbook:
        parser.error("--pdf requires --workbook")
    if args.workbook:
        seed, report = build_seed(args.workbook, args.pdf)
    else:
        seed = load_seed()
        report = {"accepted": len(seed.records), "edition": seed.edition}
    if args.seed_output:
        args.seed_output.write_text(
            seed.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    if args.report_output:
        args.report_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.apply:
        with get_engine().begin() as connection:
            report["import"] = import_catalog(
                connection, seed, actor_id="occupation-import-cli"
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
