"""Education Ministry public major-registration API; no auth or remote jobs."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexus_app.data_sync.runtime import SyncRuntimeError, _classify_http


SOURCE_URL = "https://zwfw.moe.gov.cn/zyyxzy/result.html"
PROVINCES = dict(
    zip(
        "BJ TJ HeB SX NM LN JL HLJ SH JS ZJ AH FJ JX SD HeN HuB HuN GD GX HN CQ SC GZ YN XZ SXS GS QH NX XJ XJBT".split(),
        "北京市 天津市 河北省 山西省 内蒙古自治区 辽宁省 吉林省 黑龙江省 上海市 江苏省 浙江省 安徽省 福建省 江西省 山东省 河南省 湖北省 湖南省 广东省 广西壮族自治区 海南省 重庆市 四川省 贵州省 云南省 西藏自治区 陕西省 甘肃省 青海省 宁夏回族自治区 新疆维吾尔自治区 新疆生产建设兵团".split(),
    )
)
_options_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_options_lock = threading.Lock()


class MoeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    year: int = Field(ge=2013, le=datetime.now().year, strict=True, title="年份")
    province: str = Field(min_length=1, title="省份/地区")
    major_name: str = Field(min_length=1, max_length=200, title="专业名称")
    major_code: str = Field(pattern=r"^\d{6}$", title="专业代码")

    @field_validator("province")
    @classmethod
    def known_province(cls, value: str) -> str:
        if value not in PROVINCES:
            raise ValueError("unknown Ministry province code")
        return value


def _body(response: httpx.Response) -> dict[str, Any]:
    _classify_http(response)
    try:
        body = response.json()
    except ValueError as exc:
        raise SyncRuntimeError("Ministry response is not JSON", code="invalid_response") from exc
    if not isinstance(body, dict) or body.get("success") is not True:
        retryable = isinstance(body, dict) and body.get("code") in {429, 500, 502, 503, 504}
        raise SyncRuntimeError(
            "Ministry query failed", retryable=retryable, code="moe_business_error"
        )
    return body


class MoeMajorOfferingProvider:
    page_interval = 1.0

    @property
    def result_handler(self):
        from nexus_app.data_sync.major_offering_intake import MajorOfferingResultHandler

        return MajorOfferingResultHandler()

    def get_query_schema(self) -> dict[str, Any]:
        schema = MoeQuery.model_json_schema()
        schema["properties"]["province"].update(
            enum=list(PROVINCES),
            **{"x-enum-labels": list(PROVINCES.values())},
        )
        return schema

    def validate_query(self, query: dict[str, Any]) -> dict[str, Any]:
        result = MoeQuery.model_validate(query).model_dump()
        # When dictionaries have been fetched, reject years the source does not offer.
        for expires, options in _options_cache.values():
            if expires > time.monotonic() and result["year"] not in options["years"]:
                raise ValueError("year is not available from the Ministry")
        return result

    def get_options(self, context: Any, client: httpx.Client) -> dict[str, Any]:
        with _options_lock:
            cached = _options_cache.get(context.api_server_url)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            years = _body(client.get(f"{context.api_server_url}/eduSearch/api/years"))["data"]
            provinces = _body(client.get(f"{context.api_server_url}/eduSearch/api/provinces"))[
                "data"
            ]
            if not isinstance(years, list) or not years or not all(str(y).isdigit() for y in years):
                raise SyncRuntimeError("invalid year dictionary", code="invalid_dictionary")
            if (
                not isinstance(provinces, list)
                or not provinces
                or any(
                    not isinstance(p, dict)
                    or not isinstance(p.get("code"), str)
                    or not isinstance(p.get("name"), str)
                    for p in provinces
                )
            ):
                raise SyncRuntimeError("invalid province dictionary", code="invalid_dictionary")
            options = {"years": [int(y) for y in years], "provinces": provinces}
            _options_cache[context.api_server_url] = (time.monotonic() + 3600, options)
            return options

    def fetch_pull_page(
        self,
        context: Any,
        query: dict[str, Any],
        cursor: str | None,
        client: httpx.Client,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        query = self.validate_query(query)
        try:
            state = json.loads(cursor) if cursor else {"page": 1, "received": 0}
            page = state["page"]
            if not isinstance(page, int) or page < 1:
                raise ValueError("invalid page")
        except (ValueError, KeyError, TypeError) as exc:
            raise SyncRuntimeError("invalid pull cursor", code="invalid_cursor") from exc
        params = {
            "year": query["year"],
            "province": query["province"],
            "majorCode": query["major_code"],
            "majorName": query["major_name"],
            "page": page,
            "pageSize": 50,
        }
        data = _body(
            client.get(f"{context.api_server_url}/eduSearch/api/major-register", params=params)
        ).get("data")
        try:
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                raise ValueError("invalid data")
            total = int(data["total"])
            page_size = data["pageSize"]
            if total < 0 or type(page_size) is not int or not 1 <= page_size <= 10000:
                raise ValueError("invalid pagination")
            if data["currentPage"] != page:
                raise ValueError("page mismatch")
            if cursor and (total != state["total"] or page_size != state["page_size"]):
                raise SyncRuntimeError("source total changed", code="pagination_changed")
            records = data["list"]
            expected = min(page_size, max(0, total - (page - 1) * page_size))
            if len(records) != expected:
                raise ValueError("incomplete page")
            received = state["received"] + len(records)
            if received != min(page * page_size, total):
                raise ValueError("invalid accumulated count")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SyncRuntimeError(
                "invalid Ministry pagination", code="pagination_incomplete"
            ) from exc
        next_cursor = (
            None
            if received == total
            else json.dumps(
                {
                    "page": page + 1,
                    "received": received,
                    "total": total,
                    "page_size": page_size,
                }
            )
        )
        return {"records": records, "next_cursor": next_cursor, "total": total}
