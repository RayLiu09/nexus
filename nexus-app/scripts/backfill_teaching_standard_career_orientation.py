"""Repair career-facing declarations only. Dry-run by default; never calls AI."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.storage import get_object_storage
from nexus_app.teaching_standard_library.career_orientation import refresh_career_orientation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ref-id")
    args = parser.parse_args()
    storage = get_object_storage()
    outcomes = []
    with get_session_local()() as session:
        stmt = select(models.TeachingStandardLibrary).order_by(models.TeachingStandardLibrary.id)
        if args.ref_id:
            stmt = stmt.where(models.TeachingStandardLibrary.normalized_ref_id == args.ref_id)
        for library in session.scalars(stmt).all():
            try:
                with session.begin_nested():
                    ref = session.get(models.NormalizedAssetRef, library.normalized_ref_id)
                    key = ref.object_uri.split("/", 3)[-1] if ref.object_uri.startswith("s3://") else ref.object_uri
                    payload = json.loads(storage.get_bytes(key).decode("utf-8"))
                    outcomes.append(refresh_career_orientation(session, library, payload, apply_changes=args.apply))
            except Exception as exc:
                outcomes.append({"library_id": library.id, "status": "failed", "error_type": type(exc).__name__})
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(json.dumps({"apply": args.apply, "counts": dict(Counter(r["status"] for r in outcomes)), "results": outcomes}, ensure_ascii=False))
    return int(any(r["status"] == "failed" for r in outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
