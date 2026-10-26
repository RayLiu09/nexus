#!/usr/bin/env python3
"""Generate Agent tools offline; never starts API lifespan or queries databases."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nexus-api"), str(ROOT / "nexus-app")]

from nexus_api.function_tools import chat_tools, generate_catalog


def artifacts(document):
    catalog = generate_catalog(document)
    dump = lambda value: json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    lines = ["# 基于公开 OpenAPI 生成 function tools 清单", "",
        f"自动生成；共 {len(catalog['tools'])} 个工具。来源 `/open/v1`，不包含内部接口、已退役接口、流式接口或 C 类增量接口。", "",
        "调用方按资源标签按需加载工具；使用 `responses-tools.json` 的 Responses function 格式，或 `chat-completions-tools.json` 的 Chat Completions 格式。", "",
        "参数按 `path`、`query`、`body` 分组。HTTP 执行器依据 `http-bindings.json` 调用接口，重复数组查询参数使用 repeated keys；API Key 由执行器注入，不能作为模型参数。", "",
        "`strict=false` 保留公开 OpenAPI 的可选参数、默认值和自由证据对象；执行器仍须按 OpenAPI 校验参数。外部搜索省略 auto_ingest 时，执行器必须注入 false，显式 true 可能触发入库。", "",
        "联网搜索工具 search_web_search 使用 DeepSeek Search，query 最长 90 字符，支持结果数量及日期范围；供应商凭证由服务器配置。time_range 支持 OneDay/OneWeek/OneMonth/OneYear 或 YYYY-MM-DD..YYYY-MM-DD，默认 OneYear。", "",
        "文档只读准入沿用 available/current-ref；当前 open:* 权限不提供组织过滤。业务记录按独立领域边界公开。", "",
        "当前覆盖资产中心 16 类可见资源：产教政策、产业报告、行业报告、专业简介、专业布点数据、专业教学标准、标准课程库、人才需求调研、人才培养方案、职业分类大典、职业能力分析、市场岗位、产业园区、企业数据、课程教材、教学案例。共享文档类通过 find_documents 的 resource_type/domain(s) 筛选；独立记录和投影使用各自专用工具。", "",
        "专业布点使用 list_major_offerings / aggregate_major_offerings，来源为教育部政务服务平台直接同步数据，无 AI 治理；不可用专业简介或培养方案统计替代。职业分类大典使用 query_occupation_dictionary，支持职业大类、小类、名称组合过滤，返回定义与工作任务。两类数据仅表示已入库覆盖。", "",
        "专业布点 Excel 下载由 /v1/major-offerings/export 及内部 Console 接口提供，属于二进制下载，不列为 JSON function tool。完整资源与接口映射见 [公开消费合同](../../api/public_agent_data_api.md)。", "",
        "重新生成：`nexus-api/.venv/bin/python scripts/generate_public_function_tools.py`；检查漂移：追加 `--check`。无需启动服务或读取数据库。", "",
        "| 工具 | HTTP | 资源标签 |", "| --- | --- | --- |"]
    for binding in catalog["bindings"]:
        lines.append(f"| `{binding['name']}` | `{binding['method']} {binding['path']}` | {', '.join(binding['tags'])} |")
    lines += ["", "默认排除的兼容接口：", ""]
    lines.extend(f"- `{item['method']} {item['path']}`：{item['reason']}" for item in catalog["excluded_operations"])
    return {"responses-tools.json": dump(catalog["tools"]), "chat-completions-tools.json": dump(chat_tools(catalog)),
            "http-bindings.json": dump({key: value for key, value in catalog.items() if key != "tools"}),
            "README.md": "\n".join(lines) + "\n"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", type=Path, help="Use an exported OpenAPI JSON instead of the local app schema")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/generated/public-function-tools")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.openapi:
        document = json.loads(args.openapi.read_text())
    else:
        from nexus_api.main import create_app
        document = create_app().openapi()
    output = artifacts(document)
    if args.check:
        drift = [name for name, text in output.items() if not (args.output / name).exists() or (args.output / name).read_text() != text]
        if drift:
            raise SystemExit("Generated artifacts differ: " + ", ".join(drift))
        print("Function tools artifacts match public OpenAPI")
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in output.items():
            (args.output / name).write_text(text)
        print(f"Generated {len(json.loads(output['responses-tools.json']))} tools in {args.output}")


if __name__ == "__main__":
    main()
