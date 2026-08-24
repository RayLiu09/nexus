"""Backfill deterministic province/course statistic fields; dry-run by default."""
from __future__ import annotations

import argparse
from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.institutional_statistics import course_stat_key, resolve_province_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with get_session_local()() as session:
        profiles = list(session.query(models.MajorProfile))
        plans = list(session.query(models.TalentTrainingPlan))
        profile_courses = list(session.query(models.MajorProfileCourse))
        plan_courses = list(session.query(models.TalentTrainingPlanCourse))
        updates = 0
        for row in profiles:
            value = resolve_province_name(row.region_tags or [], row.institution_name, row.source_title)
            if value != row.province_name:
                updates += 1
                if args.apply: row.province_name = value
        for row in plans:
            value = resolve_province_name(row.institution_name, row.source_title)
            if value != row.province_name:
                updates += 1
                if args.apply: row.province_name = value
        for row in profile_courses:
            value = course_stat_key(row.text)
            if value != row.course_stat_key:
                updates += 1
                if args.apply: row.course_stat_key = value
        for row in plan_courses:
            value = course_stat_key(row.course_name)
            if value != row.course_stat_key:
                updates += 1
                if args.apply: row.course_stat_key = value
        if args.apply: session.commit()
        print({"dry_run": not args.apply, "field_updates": updates, "profiles": len(profiles), "plans": len(plans), "profile_courses": len(profile_courses), "plan_courses": len(plan_courses)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
