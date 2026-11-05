"""Bounded phase-one public-tool retrieval, sharing existing query/SSE contracts."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import replace

from nexus_app.retrieval.prompt_profiles_public_tools import ANSWER_PROFILE, TOOLS_PROFILE
from nexus_app.retrieval.prompt_profiles_v2 import get_active_v2_prompt
from nexus_app.retrieval.router_v2 import RouterResult, RouterStreamEvent, StepPayload
from nexus_app.retrieval.web_search import _has_sensitive_outbound_content

from nexus_api.public_query_sources import SourceRegistry, has_data, rows_of
from nexus_api.public_query_tools import EVIDENCE_TOOLS, WEB_TOOLS, ToolFailure


LABELS = {
    "discover_data_resources": "发现可查询的业务资源", "resolve_business_entities": "解析业务实体",
    "query_market_jobs": "查询市场岗位", "aggregate_market_jobs": "统计市场岗位",
    "list_major_offerings": "查询专业布点", "aggregate_major_offerings": "统计专业布点",
    "find_documents": "查找资产文档", "search_evidence": "检索相关证据",
    "list_document_sections": "定位文档章节", "read_document_section": "读取章节证据",
    "get_outline_node_context": "补全目录上下文", "get_evidence_bundle": "补全来源证据",
    "search_web_search": "联网搜索补充资料", "search_firecrawl": "联网搜索补充资料",
    "find_textbooks": "查找课程教材", "get_textbook": "读取教材详情",
    "query_teaching_standards": "查询专业教学标准", "get_teaching_standard": "读取教学标准详情",
    "query_standard_courses": "查询标准课程", "get_standard_course": "读取课程详情",
    "query_occupation_dictionary": "查询职业分类大典", "find_major_profile_documents": "查找专业简介",
    "query_enterprises": "查询企业数据", "get_enterprise": "读取企业详情",
    "query_industrial_parks": "查询产业园区", "get_industrial_park": "读取园区详情",
    "get_market_job": "读取岗位详情", "aggregate_major_courses": "统计专业课程",
    "list_open_talent_training_plans": "查找人才培养方案", "get_open_talent_training_plan": "读取培养方案",
    "list_training_plan_courses": "查询培养方案课程", "find_ability_items": "检索职业能力条目",
    "list_ability_analyses": "查找职业能力分析", "get_ability_analysis": "读取职业能力分析",
    "list_ability_items": "读取职业能力条目", "list_ability_relations": "读取能力关系",
    "get_ability_analysis_tasks": "读取典型工作任务", "read_existing_graph": "读取已有知识图谱",
    "get_knowledge_outline": "读取知识目录", "get_task_outline": "读取任务目录",
    "get_public_knowledge_chunk": "读取证据切片", "get_available_normalized_ref": "检查标准化资产",
    "list_chunks_for_normalized_ref": "查询资产证据切片", "get_normalized_ref_content": "读取标准化正文",
    "get_public_governance_result_for_ref": "检查资产治理结果", "get_available_asset": "读取资产详情",
    "list_available_asset_versions": "查询可用资产版本", "get_job_capability_graph": "读取岗位能力图谱",
    "get_occupational_capability_graph": "读取职业能力图谱", "get_teaching_standard_knowledge_graph": "读取教学标准图谱",
    "get_open_course_knowledge_graph": "读取课程知识图谱", "get_open_position_capability_graph": "读取岗位能力图谱",
}


def query_summary(arguments):
    """Business values only; never expose raw arguments or internal anchors."""
    fields = {
        "q": "关键词", "query": "关键词", "keyword": "关键词", "title": "标题",
        "name": "名称", "major_name": "专业", "industry": "行业", "industry_name": "行业",
        "province": "省份", "province_name": "省份", "city": "城市", "city_name": "城市",
        "region": "地区", "year": "年份", "published_year": "年份",
        "resource_type": "资料类型", "topic": "主题", "tags": "标签",
        "published_from": "发布起日", "published_to": "发布止日", "page": "页码",
    }
    choices = {
        "resource_type": {"industry_policy": "产业政策", "industry_report": "产业报告",
                          "sector_report": "行业报告", "industry_regulation_standard": "法规标准",
                          "major_profile": "专业简介", "teaching_standard": "教学标准",
                          "talent_demand_report": "人才需求报告", "talent_training_plan": "培养方案",
                          "competency_analysis": "职业能力分析", "course_textbook": "课程教材",
                          "teaching_case": "教学案例"},
        "topic": {"low_altitude": "低空经济", "finance_commerce": "财经商贸"},
    }
    parts = []
    for group in ("query", "body"):
        values = arguments.get(group)
        if not isinstance(values, dict):
            continue
        for key, label in fields.items():
            value = values.get(key)
            if isinstance(value, list):
                value = "、".join(str(v) for v in value[:3] if isinstance(v, str))
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                continue
            if key in choices:
                value = choices[key].get(value, "")
            value = str(value).strip()
            if (not value or _has_sensitive_outbound_content(value)
                    or re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", value, re.I)):
                continue
            value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
            parts.append(f"{label}：{value[:60]}{'…' if len(value) > 60 else ''}")
    return "；".join(parts[:6])


def compact(value, max_chars=18000):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return value
    if isinstance(value, str):
        return value[:max_chars] + "[截断]"
    if isinstance(value, list):
        subset = value[:8]
        return {"items": [compact(item, max(100, max_chars // 10)) for item in subset],
                "truncated": True, "original_count": len(value)}
    if isinstance(value, dict):
        budget = max(100, max_chars // max(1, len(value)) - 30)
        return {**{k: compact(v, budget) for k, v in value.items()}, "context_truncated": True}
    return value


def render(template, **variables):
    # Single-pass substitution: data containing {{...}} never becomes template code.
    return re.sub(r"\{\{\s*([A-Z_]+)\s*\}\}", lambda m: str(variables.get(m[1], m[0])), template)


def validate_citations(markdown, sources):
    allowed = {s["citation_id"] for s in sources}
    invalid = []
    def substitute(match):
        if match[1] in allowed:
            return match[0]
        invalid.append(match[1])
        return "[引用不可用]"
    markdown = re.sub(r"\[(\d+)\](?!\()", substitute, markdown)
    # Model-created links are not evidence. UI navigation uses the source registry.
    markdown = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    return markdown, bool(invalid)


class PublicQueryRuntime:
    def __init__(self, executor, llm, settings):
        self.executor, self.llm, self.settings = executor, llm, settings
        self.cancelled = threading.Event()
        self.turn_id = str(uuid.uuid4())
        self.sequence = 0
        self.active_step = None
        self.web_search_enabled = False

    def cancel(self):
        self.cancelled.set()

    def _event(self, kind, **kwargs):
        if kind == "step":
            step = kwargs["step"]
            if step.status == "running":
                self.active_step = step
                self._step_started[step.id] = time.monotonic()
            else:
                started = self._step_started.pop(step.id, None)
                if started is not None:
                    self.performance["stages"].append({
                        "action_id": step.id, "type": step.action_type,
                        "tool": step.tool_name, "status": step.status,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    })
                if self.active_step is not None and self.active_step.id == step.id:
                    self.active_step = None
        elif kind == "chunk" and kwargs.get("text") and self.performance["first_answer_ms"] is None:
            self.performance["first_answer_ms"] = round((time.monotonic() - self.started) * 1000, 2)
        self.sequence += 1
        return RouterStreamEvent(type=kind, event_id=str(uuid.uuid4()),
                                 sequence=self.sequence, turn_id=self.turn_id, **kwargs)

    def _check(self):
        if self.cancelled.is_set():
            raise ToolFailure("cancelled")
        if time.monotonic() - self.started > 180:
            raise ToolFailure("execution_budget_exhausted")

    def _invoke(self, name, arguments, *, parent=None):
        self._check()
        cache_key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if cache_key in self._completed_calls:
            payload, previous = self._completed_calls[cache_key]
            previous["reuse_count"] = previous.get("reuse_count", 0) + 1
            return payload
        if len(self.calls) >= 16:
            raise ToolFailure("tool_budget_exhausted")
        action = f"tool-{len(self.calls) + 1}"
        started = int(time.time() * 1000)
        step = StepPayload(id=action, status="running", label=LABELS.get(name, "查询业务数据"),
                           tool_name=name, action_type="web_search" if name in WEB_TOOLS else "tool",
                           parent_action_id=parent, started_at_ms=started,
                           input={"tool": name, "query_summary": query_summary(arguments)})
        yield self._event("step", step=step)
        call = {"tool": name, "status": "error", "arguments": arguments}
        self.calls.append(call)
        try:
            self._check()
            payload = self.executor.execute(name, arguments)
            self._check()
            call.update(status="success" if has_data(payload) else "empty", result=compact(payload))
            if name not in {"discover_data_resources", "resolve_business_entities"}:
                self.local_payloads.append((name, payload))
            before = len(self.registry.sources)
            call["citation_ids"] = self.registry.add(name, arguments, payload)
            self._observed.update(re.findall(r'"(?:id|\w+_id)"\s*:\s*"([^"\\]+)"', json.dumps(payload)))
            output = {"tool": name, "outcome": call["status"],
                      "source_count": len(call["citation_ids"]),
                      "new_source_count": len(self.registry.sources) - before,
                      "total_source_count": len(self.registry.sources)}
            if name in WEB_TOOLS:
                ingestion = payload.get("data", {}).get("ingestion", {})
                output["ingestion"] = {k: ingestion.get(k) for k in ("enabled", "submitted_count", "filtered_count")}
            self._completed_calls[cache_key] = (payload, call)
            yield self._event("step", step=replace(step, status="completed", output=output,
                                                   completed_at_ms=int(time.time() * 1000)))
            return payload
        except ToolFailure as exc:
            code = str(exc)
            call["error"] = code
            self.warnings.append(code)
            yield self._event("step", step=replace(step, status="cancelled" if code == "cancelled" else "failed",
                                                   error=code, completed_at_ms=int(time.time() * 1000)))
            if code in {"cancelled", "execution_budget_exhausted"}:
                raise
            return None

    def _context(self):
        data = compact(self.calls, 50000)
        encoded = json.dumps(data, ensure_ascii=False)
        if len(encoded) > 70000:
            # Preserve call outcomes/IDs rather than cutting JSON mid-token.
            data = [{"tool": c["tool"], "status": c["status"], "error": c.get("error"),
                     "citation_ids": c.get("citation_ids", []),
                     "result_preview": json.dumps(c.get("result"), ensure_ascii=False)[:1000],
                     "context_truncated": True}
                    for c in self.calls]
            encoded = json.dumps(data, ensure_ascii=False)
        return encoded

    def _document_candidates(self, query):
        terms = set(re.findall(r"[a-zA-Z0-9]{2,}", query))
        for phrase in re.findall(r"[\u4e00-\u9fff]+", query):
            terms.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
        def rank(source):
            return sum(len(t) for t in terms if t.lower() in source["title"].lower())
        candidates = [s for s in self.registry.sources if s.get("normalized_ref_id")
                      and s["source_type"] == "document" and (rank(s) or s["evidence_level"] == "content")]
        return sorted(candidates, key=rank, reverse=True)

    def _use_direct_document_evidence(self, query):
        # Graph/chapter questions still need the specialist evidence planner.
        specialist = re.search(r"图谱|知识图|关系图|能力图|任务树|目录|章节|上下文|第[一二三四五六七八九十百\d]+[章节]|\b(?:graph|outline|chapter|section)\b", query, re.I)
        return (not specialist and "get_normalized_ref_content" in self.executor.tools
                and bool(self._document_candidates(query)))

    def _complete_evidence(self, query):
        """At most three relevant content reads, using already observed anchors."""
        completed = {c["arguments"].get("path", {}).get("ref_id") for c in self.calls
                     if c["status"] == "success" and c["tool"] in {
                         "read_document_section", "get_outline_node_context", "get_normalized_ref_content"}}
        candidates = [s for s in self._document_candidates(query) if s["normalized_ref_id"] not in completed]
        for source in candidates[:3]:
            yield from self._invoke("get_normalized_ref_content", {
                "path": {"ref_id": source["normalized_ref_id"]},
            })
        # A missing stored body must not make the faster path weaker than the
        # chapter API. Fall back once, using returned anchors and remaining budget.
        if (candidates and self.performance["evidence_strategy"] == "direct_document_content"
                and not any(s["evidence_level"] == "content" for s in self._document_candidates(query))
                and len(self.calls) <= 14
                and {"list_document_sections", "read_document_section"} <= self.executor.tools.keys()):
            ref = candidates[0]["normalized_ref_id"]
            sections = yield from self._invoke("list_document_sections", {
                "path": {"ref_id": ref}, "query": {"limit": 5},
            })
            items = rows_of((sections or {}).get("data"))
            if items and items[0].get("id"):
                yield from self._invoke("read_document_section", {
                    "path": {"ref_id": ref, "section_id": items[0]["id"]}, "query": {"max_chars": 12000},
                })
                self.performance["evidence_strategy"] = "direct_document_section_fallback"

    def _answer_context(self):
        """Call outcomes/filters once; evidence itself lives in the source list.

        Full aggregate payloads remain here: their coverage/missingness metrics
        must not be inferred from the source list or a paginated record sample.
        """
        summaries = []
        for call in self.calls:
            item = {k: call[k] for k in ("tool", "status", "arguments", "citation_ids", "error") if k in call}
            result = call.get("result") or {}
            if call["tool"].startswith("aggregate_"):
                item["result"] = result
            elif isinstance(result, dict):
                item["meta"] = result.get("meta")
                item["aggregations"] = result.get("aggregations")
                data = result.get("data")
                if isinstance(data, dict):
                    item["coverage"] = {k: data[k] for k in ("total", "total_count", "count", "truncated", "available") if k in data}
            summaries.append(item)
        if len(json.dumps(summaries, ensure_ascii=False)) > 50000:
            budget = max(1000, 40000 // max(1, len(summaries)))
            for item in summaries:
                if "result" in item:
                    item["result"] = compact(item["result"], budget)
        return json.dumps(summaries, ensure_ascii=False)

    def _answer_sources(self):
        technical = {"id", "asset_id", "version_id", "asset_version_id", "normalized_ref_id", "raw_object_id",
                     "chunk_id", "nexus_chunk_id", "object_uri", "capabilities", "download_url_endpoint"}
        def business(value):
            if isinstance(value, dict):
                return {k: business(v) for k, v in value.items() if k not in technical and not k.endswith("_endpoint")}
            if isinstance(value, list):
                return [business(v) for v in value]
            return value
        sources = []
        for source in self.registry.sources:
            item = {k: source[k] for k in ("citation_id", "source_type", "title", "evidence_level", "url", "scope", "published_at", "collected_at", "truncated") if k in source}
            if source["source_type"] == "aggregate":
                item["excerpt"] = "统计事实及缺失情况见对应工具结果，保持相同查询口径。"
            elif source["evidence_level"] in {"metadata", "record"}:
                try:
                    item["data"] = compact(business(json.loads(source["excerpt"])), 3000)
                except (ValueError, TypeError):
                    item["excerpt"] = source["excerpt"][:5000]
            else:
                # Keep the acquired body once, including text formerly duplicated
                # in TOOL_RESULTS. This is not a shorter-answer/token-limit change.
                item["excerpt"] = source["excerpt"][:5000]
            sources.append(item)
        # Keep ordinary acquired bodies (up to 5k each) once, bounding unusually
        # large semantic-hit lists without dropping citation IDs or whole sources.
        excerpts = [s for s in sources if "excerpt" in s and s["source_type"] != "aggregate"]
        overhead = len(json.dumps([{k: v for k, v in s.items() if k != "excerpt"} for s in sources], ensure_ascii=False))
        allowance = min(5000, max(500, (110000 - overhead) // max(1, len(excerpts))))
        for source in excerpts:
            if len(source["excerpt"]) > allowance:
                source["excerpt"] = source["excerpt"][:allowance]
                source["truncated"] = True
        return sources

    def _select(self, profile, query, names, stage):
        self._check()
        prompt = render(profile.prompt_template, QUERY=query, RESOURCE_SUMMARY=stage,
                        TOOL_RESULTS=self._context())
        definitions = self.executor.definitions(names)
        self.performance["planning_requests"].append({
            "prompt_chars": len(prompt), "tool_schema_chars": len(json.dumps(definitions, ensure_ascii=False)),
            "tool_count": len(definitions),
        })
        return self.llm.call_with_tools(
            self.settings.default_governance_model,
            [{"role": "system", "content": prompt}],
            tools=definitions, tool_choice="auto", max_tokens=2500,
            temperature=profile.temperature,
        )

    def _web_reason(self, query):
        if not self.web_search_enabled:
            return None
        if re.search(r"仅(?:限|用|查|搜索)?(?:本地|平台|内部)|只(?:用|查|搜索)(?:本地|平台|内部)|不要联网|不联网|禁止联网|local.only", query, re.I):
            self.warnings.append("external_search_blocked_local_scope")
            return None
        for call in self.calls:
            scope = call["arguments"].get("query") or {}
            if isinstance(scope, dict) and any(scope.get(k) for k in (
                "asset_ids", "normalized_ref_ids", "outline_node", "task_outline_node")):
                self.warnings.append("external_search_blocked_local_scope")
                return None
        if _has_sensitive_outbound_content(query):
            self.warnings.append("external_search_blocked_sensitive_query")
            return None
        return "user_enabled_web_search"

    def run(self, session, **kwargs):
        result = None
        for event in self.run_stream(session, **kwargs):
            if event.result is not None:
                result = event.result
        if result is None:
            raise ToolFailure("cancelled")
        return result

    def run_stream(self, session, *, query, route, caller_type):
        self.started = time.monotonic()
        self._step_started = {}
        self.performance = {"stages": [], "planning_requests": [], "first_answer_ms": None,
                            "evidence_strategy": "model_selected"}
        self.calls, self.warnings, self.local_payloads = [], [], []
        self._completed_calls = {}
        self.registry, self._observed = SourceRegistry(), set()
        markdown, fallback = "", None
        profile_versions = {}
        yield self._event("meta", meta={"engine": "public_tools_v1", "request_id": self.executor.trace_id,
                                       "turn_id": self.turn_id, "intent": "public_tools",
                                       "web_search_enabled": self.web_search_enabled})
        try:
            planner = get_active_v2_prompt(session, TOOLS_PROFILE)
            answer = get_active_v2_prompt(session, ANSWER_PROFILE)
            profile_versions = {p.profile_name: {"version": p.profile_version, "hash": p.content_hash}
                                for p in (planner, answer)}
            # Detach scalar configuration before HTTP/model calls. No Session is
            # shared by parallel tools; this phase executes calls sequentially.
            from types import SimpleNamespace
            planner, answer = [SimpleNamespace(prompt_template=p.prompt_template, temperature=p.temperature)
                               for p in (planner, answer)]
            discovery = yield from self._invoke("discover_data_resources", {})
            if discovery is None:
                self.warnings.append("resource_discovery_failed")
            primary = set(self.executor.tools) - EVIDENCE_TOOLS - WEB_TOOLS
            for round_no, names in enumerate((primary, primary, EVIDENCE_TOOLS), 1):
                if round_no == 3 and self._use_direct_document_evidence(query):
                    self.performance["evidence_strategy"] = "direct_document_content"
                    break
                if round_no > 1 and any(c["tool"].startswith("aggregate_") and c["status"] in {"success", "empty"} for c in self.calls):
                    break  # exact aggregate evidence needs no extra model planning
                self._check()
                planning_labels = ("分析问题并选择查询方式", "根据已有结果补充查询", "检查并补全证据")
                step = StepPayload(id=f"planning-{round_no}", status="running", label=planning_labels[round_no - 1],
                                   action_type="planning", started_at_ms=int(time.time() * 1000))
                yield self._event("step", step=step)
                stage = ("初次查询，必要时解析实体；业务记录覆盖所有公开资源。" if round_no == 1 else
                         "根据已有结果补充查询，只添加尚未执行的不同关键词/筛选条件或按已返回 ID 查询详情；相同工具与参数会复用之前结果，勿重复请求。" if round_no == 2 else
                         "证据补全阶段，只读取与问题相关的实际返回 ID；已有足够正文/统计时无需再调用。")
                try:
                    selection = self._select(planner, query, names, stage)
                except Exception:
                    self.warnings.append("tool_selection_failed")
                    yield self._event("step", step=replace(step, status="failed", error="tool_selection_failed",
                                                           completed_at_ms=int(time.time() * 1000)))
                    break
                self._check()
                yield self._event("step", step=replace(step, status="completed", completed_at_ms=int(time.time() * 1000),
                                                       output={"selected_tools": [t.name for t in selection.tool_calls]}))
                if not selection.tool_calls:
                    if round_no == 1:
                        # General knowledge questions still perform a real scoped local search.
                        yield from self._invoke("search_evidence", {"query": {"q": query[:1024],
                                                "similarity_threshold": 0.5, "top_k": 8}})
                    continue
                for tool in selection.tool_calls[:3 if round_no == 3 else 4]:
                    self._check()
                    if tool.name not in names:
                        self.warnings.append("tool_not_in_current_stage")
                        continue
                    try:
                        args = json.loads(tool.arguments)
                    except ValueError:
                        args = None
                    if not isinstance(args, dict):
                        self.warnings.append("invalid_tool_arguments")
                        continue
                    if round_no == 3 and isinstance(args.get("path"), dict) and any(str(v) not in self._observed for k, v in args["path"].items()
                                             if k not in {"outline_type"}):
                        self.warnings.append("unobserved_evidence_anchor")
                        continue
                    yield from self._invoke(tool.name, args, parent=step.id)
            fallback = self._web_reason(query)
            if fallback:
                yield from self._invoke("search_web_search", {"body": {"query": query[:90], "count": 10}})
            yield from self._complete_evidence(query)
            self._check()
            yield self._event("meta", meta={"citations": self.registry.sources, "citation_phase": "candidates", "turn_id": self.turn_id})
            if not self.registry.sources:
                markdown = "未找到可引用的内容。请补充关键词、专业名称或查询范围后重试。"
                if self.warnings:
                    markdown += "\n\n部分查询未能完成，请查看执行过程后重试。"
                yield self._event("chunk", text=markdown)
            else:
                step = StepPayload(id="compose", status="running", label="依据证据生成回答", action_type="compose",
                                   started_at_ms=int(time.time() * 1000))
                yield self._event("step", step=step)
                citation_context = self._answer_sources()
                call_context = self._answer_context()
                prompt = render(answer.prompt_template, QUERY=query, TOOL_RESULTS=call_context,
                                CITATIONS=json.dumps(citation_context, ensure_ascii=False))
                self.performance["compose_prompt_chars"] = len(prompt)
                self.performance["compose_call_summary_chars"] = len(call_context)
                for text in self.llm.call_stream(self.settings.default_governance_model,
                                                [{"role": "system", "content": prompt}],
                                                temperature=answer.temperature, max_tokens=4500):
                    self._check()
                    markdown += text
                    yield self._event("chunk", text=text)
                markdown, invalid = validate_citations(markdown, self.registry.sources)
                if invalid:
                    self.warnings.append("invalid_citation_removed")
                if not re.search(r"\[\d+\]", markdown):
                    self.warnings.append("answer_missing_citations")
                    markdown += "\n\n> 回答未提供有效的行内引用，请谨慎核对关键信息。"
                yield self._event("step", step=replace(step, status="completed", completed_at_ms=int(time.time() * 1000)))
        except GeneratorExit:
            self.cancel()
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, ToolFailure) else "query_execution_failed"
            self.warnings.append(code)
            fallback = code
            if self.active_step is not None:
                yield self._event("step", step=replace(self.active_step,
                    status="cancelled" if code == "cancelled" else "failed", error=code,
                    completed_at_ms=int(time.time() * 1000)))
            if code == "cancelled":
                return
            # Failed model output must not survive as an uncited answer.
            markdown = "本次查询未能完成，请查看执行过程或稍后重试。"
            yield self._event("error", reason=code)
        cited_ids = set(re.findall(r"\[(\d+)\](?!\()", markdown))
        citations = tuple(s for s in self.registry.sources if s["citation_id"] in cited_ids)
        self.performance["total_ms"] = round((time.monotonic() - self.started) * 1000, 2)
        self.performance["http_call_count"] = len(self.calls)
        result = RouterResult(
            markdown=markdown, raw_markdown=markdown, intent="public_tools", intent_confidence=0,
            invoked_tools=[c["tool"] for c in self.calls], fallback_reason=fallback,
            warnings=tuple(dict.fromkeys(self.warnings)), citations=citations,
            audit_summary={"route": route, "caller_type": caller_type, "query_route": "public_tools_v1",
                           "request_id": self.executor.trace_id, "turn_id": self.turn_id,
                           "invoked_tools": [c["tool"] for c in self.calls],
                           "tool_outcomes": [{"tool": c["tool"], "status": c["status"], "error": c.get("error")}
                                             for c in self.calls],
                           "reused_tool_call_count": sum(c.get("reuse_count", 0) for c in self.calls),
                           "citation_count": len(citations), "candidate_source_count": len(self.registry.sources),
                           "web_search_enabled": self.web_search_enabled, "fallback_reason": fallback,
                           "ingest_search_results": self.settings.ingest_search_results,
                           "prompt_profiles": profile_versions, "performance": self.performance},
        )
        yield self._event("final", result=result)
