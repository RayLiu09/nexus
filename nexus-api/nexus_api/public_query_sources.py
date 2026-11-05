"""Bounded, deduplicated candidate evidence from successful public API results."""
from __future__ import annotations

import json
from urllib.parse import urlsplit


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def rows_of(data):
    if isinstance(data, list):
        return [v for v in data if isinstance(v, dict)]
    if isinstance(data, dict):
        for key in ("results", "items", "records", "groups", "references", "resolutions", "chunks", "nodes"):
            if isinstance(data.get(key), list):
                return [v for v in data[key] if isinstance(v, dict)]
        return [data] if data else []
    return []


def has_data(payload):
    data = payload.get("data")
    if not data:
        return False
    if isinstance(data, dict):
        if data.get("available") is False or data.get("restricted") is True:
            return False
        for key in ("results", "items", "records", "groups", "references", "chunks", "resolutions", "nodes"):
            if isinstance(data.get(key), list):
                return any(r and not r.get("restricted") and r.get("status") != "not_found"
                           for r in data[key] if isinstance(r, dict))
    return True


class SourceRegistry:
    def __init__(self):
        self.sources = []
        self.citation_ids_by_key = {}

    def add(self, tool, arguments, payload):
        if ((not has_data(payload) and not tool.startswith("aggregate_"))
                or tool in {"discover_data_resources", "resolve_business_entities"}):
            return []
        matched_ids = []
        data = payload["data"]
        if tool.startswith("aggregate_"):
            rows = [{"title": "查询结果统计", "content": json.dumps(data, ensure_ascii=False)}]
            kind = "aggregate"
        else:
            rows = rows_of(data)
            kind = "external_web" if tool.startswith("search_") and tool != "search_evidence" else "record"
        if tool == "get_available_asset" and isinstance(data, dict) and data.get("current_normalized_ref"):
            rows = [{**data["current_normalized_ref"], "normalized_ref_id": data["current_normalized_ref"].get("id"),
                     "asset_id": data.get("asset", {}).get("id")}]
        for row in rows[:20]:
            if row.get("restricted") or row.get("status") == "not_found" or row.get("truncated") is True and len(row) == 2:
                continue
            ref_id = row.get("normalized_ref_id") or arguments.get("path", {}).get("ref_id")
            if tool == "get_available_normalized_ref":
                ref_id = ref_id or row.get("id")
            chunk_id = row.get("nexus_chunk_id") or row.get("chunk_id")
            if tool == "get_public_knowledge_chunk":
                chunk_id = chunk_id or row.get("id")
            source_kind = "document" if ref_id else kind
            title_fields = {**(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}), **row}
            title = next((title_fields.get(k) for k in (
                "title", "standard_title", "textbook_title", "job_title", "enterprise_name",
                "park_name", "course_name", "major_name", "name",
            ) if isinstance(title_fields.get(k), str) and title_fields[k]), tool)
            content = next((row.get(k) for k in ("body_markdown", "content", "text", "snippet", "summary", "description", "introduction")
                            if isinstance(row.get(k), str) and row[k]), None)
            evidence_level = (
                "content" if source_kind == "document" and content and (
                    tool not in {"find_documents", "find_major_profile_documents", "get_available_asset", "get_available_normalized_ref"}
                    or row.get("body_markdown")
                ) else
                "metadata" if source_kind == "document" else source_kind
            )
            if content is None:
                content = json.dumps(row, ensure_ascii=False)
            url = safe_url(row.get("url") or row.get("source_url"))
            if source_kind == "external_web" and not url:
                continue
            # A document keeps one stable ID across filters, metadata and body
            # reads. Query scope is identity only for aggregate facts.
            identity = (("document", ref_id) if ref_id else
                        ("web", url) if url and source_kind == "external_web" else
                        ("chunk", chunk_id) if chunk_id else
                        (tool, row.get("id") or row.get("result_id") or url or
                         json.dumps(arguments, sort_keys=True, ensure_ascii=False)))
            existing_id = self.citation_ids_by_key.get(identity)
            if existing_id:
                existing = next(s for s in self.sources if s["citation_id"] == existing_id)
                if evidence_level == "content":
                    previous = existing["excerpt"] if existing["evidence_level"] == "content" else ""
                    merged = previous
                    if not previous:
                        merged = content
                    elif content not in previous:
                        merged = previous + "\n\n" + content
                    existing["excerpt"] = merged[:12000]
                    existing.update(evidence_level="content", truncated=bool(
                        existing.get("truncated") or row.get("truncated") or row.get("content_truncated") or len(merged) > 12000))
                for key, value in {"asset_id": row.get("asset_id"), "version_id": row.get("version_id"),
                                   "url": url, "section_id": arguments.get("path", {}).get("section_id")}.items():
                    if value:
                        existing[key] = value
                if existing["title"] == existing["tool"] and title != tool:
                    existing["title"] = title
                matched_ids.append(existing_id)
                continue
            # Reserve ten slots for explicit web results; local metadata cannot
            # consume the web allowance. Existing references can always enrich.
            web = source_kind == "external_web"
            if sum((s["source_type"] == "external_web") == web for s in self.sources) >= (10 if web else 30):
                continue
            citation_id = str(len(self.sources) + 1)
            self.citation_ids_by_key[identity] = citation_id
            matched_ids.append(citation_id)
            self.sources.append({
                "citation_id": citation_id, "source_type": source_kind,
                "title": title, "excerpt": content[:12000], "url": url, "evidence_level": evidence_level,
                "tool": tool, "record_id": row.get("id"),
                "asset_id": row.get("asset_id") or (row.get("id") if tool in {"find_documents", "find_major_profile_documents"} else None),
                "version_id": row.get("version_id") or row.get("asset_version_id"),
                "normalized_ref_id": ref_id, "chunk_id": chunk_id,
                "section_id": arguments.get("path", {}).get("section_id"),
                "locator": row.get("locator") or row.get("knowledge_outline") or {},
                "scope": arguments.get("query", {}),
                "published_at": row.get("published_at") or (row.get("business_metadata") or {}).get("publish_date") or (row.get("metadata") or {}).get("published_at"),
                "collected_at": row.get("collected_at"),
                "truncated": bool(row.get("truncated") or row.get("content_truncated") or len(content) > 12000),
                "next_offset": row.get("next_offset"),
            })
        return list(dict.fromkeys(matched_ids))
