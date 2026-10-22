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
        "文档只读准入沿用 available/current-ref；当前 open:* 权限不提供组织过滤。业务记录按独立领域边界公开。", "",
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
