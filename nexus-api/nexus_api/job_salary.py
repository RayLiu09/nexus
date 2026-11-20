"""Conservative source salary parsing, without changing stored job facts."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
import unicodedata

from sqlalchemy import case, func

from nexus_api.market_job_queries import job_facts
from nexus_app import models

NUMBER = r"\d{1,9}(?:\.\d{1,4})?"
SALARY = re.compile(
    rf"(?P<low>{NUMBER})(?P<unit1>万元|万|千元|千|k|元)?"
    rf"(?:-(?P<high>{NUMBER})(?P<unit2>万元|万|千元|千|k|元)?)?"
    r"(?P<period>/月|每月|月薪|/年|每年|年薪)?"
    r"(?:[·•*×](?P<payments>\d{1,2})薪)?"
)
SCALES = {"元": Decimal(1), "k": Decimal(1000), "千": Decimal(1000),
          "千元": Decimal(1000), "万": Decimal(10000), "万元": Decimal(10000)}
BUCKETS = [("lt_3000", 0, 3000), ("3000_5000", 3000, 5000),
           ("5000_8000", 5000, 8000), ("8000_10000", 8000, 10000),
           ("10000_15000", 10000, 15000), ("15000_20000", 15000, 20000),
           ("20000_30000", 20000, 30000), ("gte_30000", 30000, None)]


@dataclass(frozen=True)
class MonthlySalary:
    lower: Decimal
    upper: Decimal
    period_basis: str
    payments_per_year: int | None

    @property
    def midpoint(self):
        return (self.lower + self.upper) / 2


def parse_salary(raw: str | None, assume_monthly=False):
    """Return (parsed, exclusion_reason); no working-time/currency inference."""
    if raw is None or not raw.strip():
        return None, "missing"
    text = unicodedata.normalize("NFKC", raw).lower()
    text = re.sub(r"\s+", "", text).replace("～", "-").replace("~", "-").replace("—", "-").replace("–", "-")
    if text == "面议":
        return None, "negotiable"
    if re.search(r"/(?:天|日|时|小时|周|次)|每(?:天|日|时|小时|周|次)", text):
        return None, "unsupported_period"
    if "以上" in text or "以下" in text or "+" in text:
        return None, "open_range"
    # Support explicit leading period labels without assigning a period twice.
    prefix = None
    for label, period in (("月薪", "/月"), ("年薪", "/年")):
        if text.startswith(label):
            prefix, text = period, text[len(label):]
            break
    match = SALARY.fullmatch(text)
    if match is None:
        return None, "unsupported_format"
    low, high, unit1, unit2, period, payments = match.group(
        "low", "high", "unit1", "unit2", "period", "payments",
    )
    if prefix and period:
        return None, "unsupported_format"
    period = prefix or period
    if not unit1 and not unit2:
        return None, "missing_currency_unit"
    if period is None and not assume_monthly:
        return None, "unspecified_period"
    unit1, unit2 = unit1 or unit2, unit2 or unit1
    lower = Decimal(low) * SCALES[unit1]
    upper = Decimal(high or low) * SCALES[unit2]
    if lower <= 0 or upper < lower:
        return None, "invalid_range"
    if payments is not None and not 1 <= int(payments) <= 36:
        return None, "invalid_payments"
    annual = period in ("/年", "每年", "年薪")
    if annual and payments:
        return None, "conflicting_period"
    if annual:
        lower, upper = lower / 12, upper / 12
    return MonthlySalary(lower, upper,
        "annual_divided_by_12" if annual else "explicit_monthly" if period else "assumed_monthly",
        int(payments) if payments else None), None


def money(value):
    return float(value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def salary_frequency_statement(filters):
    salary = models.RawJob.salary_raw
    return job_facts(filters, salary, func.count().label("record_count")).group_by(salary)


def salary_top_statement(filters, candidates, top_n):
    job = models.RawJob
    # All raw strings with equal numerical bounds have equal rank, so ID is
    # the final stable tiebreaker even across different source expressions.
    ranks = {bounds: rank for rank, bounds in enumerate(sorted(set(candidates.values()), reverse=True))}
    order = case({raw: ranks[bounds] for raw, bounds in candidates.items()}, value=job.salary_raw)
    return job_facts(filters, job.id, job.title_raw, job.title_normalized, job.company_name_raw,
        job.region, job.company_industry_raw, job.degree_raw, job.experience_raw, job.salary_raw,
    ).where(job.salary_raw.in_(candidates)).order_by(order, job.id.desc()).limit(top_n)


def analyze_salaries(session, filters, top_n, assume_monthly):
    frequencies = session.execute(salary_frequency_statement(filters)).all()
    excluded = Counter()
    parsed = {}
    eligible = assumed = annual = matched = 0
    counts = {key: 0 for key, _, _ in BUCKETS}
    for raw, count in frequencies:
        matched += count
        salary, reason = parse_salary(raw, assume_monthly)
        if reason:
            excluded[reason] += count
            continue
        parsed[raw] = (salary, count)
        eligible += count
        assumed += count if salary.period_basis == "assumed_monthly" else 0
        annual += count if salary.period_basis == "annual_divided_by_12" else 0
        for key, lower, upper in BUCKETS:
            if salary.midpoint >= lower and (upper is None or salary.midpoint < upper):
                counts[key] += count
                break
    candidates = {}
    covered = 0
    cutoff = None
    for raw, (salary, count) in sorted(parsed.items(), key=lambda item: (
        item[1][0].lower, item[1][0].upper,
    ), reverse=True):
        bounds = (salary.lower, salary.upper)
        if covered >= top_n and bounds != cutoff:
            break
        candidates[raw] = bounds
        covered += count
        cutoff = bounds
    top = []
    if candidates:
        for row in session.execute(salary_top_statement(filters, candidates, top_n)).mappings():
            salary = parsed[row["salary_raw"]][0]
            top.append({"id": row["id"], "job_title": row["title_raw"],
                "title_normalized": row["title_normalized"], "company_name": row["company_name_raw"],
                "region": row["region"], "industry": row["company_industry_raw"],
                "education": row["degree_raw"], "experience_requirement": row["experience_raw"],
                "salary_range": row["salary_raw"], "monthly_lower": money(salary.lower),
                "monthly_upper": money(salary.upper), "period_basis": salary.period_basis,
                "payments_per_year": salary.payments_per_year})
    return {"sample_count": matched, "eligible_count": eligible, "excluded_count": matched - eligible,
        "exclusion_counts": dict(sorted(excluded.items())), "assumed_monthly_count": assumed,
        "annual_converted_count": annual,
        "buckets": [{"code": key, "lower_inclusive": lower, "upper_exclusive": upper,
                     "record_count": counts[key]} for key, lower, upper in BUCKETS],
        "top_jobs": top, "top_n": top_n,
        "methodology": {"currency": "CNY", "unit": "yuan_per_month", "assume_monthly": assume_monthly,
            "ranking": "monthly_lower_desc,monthly_upper_desc,id_desc",
            "bucket_basis": "unrounded_monthly_range_midpoint",
            "annual_conversion": "quoted_annual_range_divided_by_12",
            "extra_payments": "preserved_but_not_included_in_monthly_base",
            "source": "raw_jobs", "deduplication_key": "raw_jobs.id", "count_unit": "records",
            "coverage": "ingested_records_only", "region_semantics": "collection_scope_not_work_location",
            "industry_semantics": "unmodified_source_industry_text",
            "filters": filters.model_dump(mode="json", exclude_none=True)}}
