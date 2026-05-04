from __future__ import annotations

import json
from uuid import uuid4
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from nexus_app.config import Settings, get_settings
from nexus_app.storage import checksum_value


@dataclass(frozen=True)
class ParseResult:
    content: bytes
    content_type: str
    parse_mode: str
    metadata: dict[str, object]


class MinerUAdapter(Protocol):
    def parse(self, filename: str, content: bytes, content_type: str | None = None) -> ParseResult:
        ...


class FakeMinerUAdapter:
    def parse(self, filename: str, content: bytes, content_type: str | None = None) -> ParseResult:
        text = content.decode("utf-8", errors="ignore")
        title = filename.rsplit("/", 1)[-1]
        result = {
            "schema_version": "mineru-fake-v1",
            "title": title,
            "markdown": f"# {title}\n\n{text[:4000]}",
            "content_checksum": checksum_value(content),
            "blocks": [
                {
                    "block_id": "block-001",
                    "type": "paragraph",
                    "text": text[:4000],
                }
            ],
        }
        return ParseResult(
            content=json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            content_type="application/json",
            parse_mode="fake",
            metadata={"adapter": "fake", "source_filename": title},
        )


class MinerUHttpAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.mineru_endpoint:
            raise ValueError("MINERU_ENDPOINT is not configured")

    def health(self) -> dict[str, object]:
        url = urljoin(self.settings.mineru_endpoint.rstrip("/") + "/", "health")
        request = Request(url, method="GET")
        with urlopen(request, timeout=10) as response:
            body = response.read(4096)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"status": "ok", "raw_bytes": len(body)}

    def parse(self, filename: str, content: bytes, content_type: str | None = None) -> ParseResult:
        boundary = f"----nexus-mineru-{uuid4().hex}"
        form = _multipart_form(
            boundary,
            fields={
                "backend": "hybrid-auto-engine",
                "parse_method": "auto",
                "formula_enable": "true",
                "table_enable": "true",
                "return_md": "true",
                "return_middle_json": "true",
                "return_model_output": "false",
                "return_content_list": "false",
                "return_images": "false",
                "response_format_zip": "false",
                "return_original_file": "false",
                "start_page_id": "0",
                "end_page_id": "99999",
            },
            list_fields={"lang_list": ["ch"]},
            files=[
                {
                    "name": "files",
                    "filename": filename,
                    "content": content,
                    "content_type": content_type or "application/octet-stream",
                }
            ],
        )
        url = urljoin(self.settings.mineru_endpoint.rstrip("/") + "/", "file_parse")
        request = Request(
            url,
            data=form,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "nexus-mineru-adapter/1.0",
            },
        )
        with urlopen(request, timeout=self.settings.mineru_timeout) as response:
            body = response.read()
            response_type = response.headers.get("content-type") or "application/octet-stream"
        return ParseResult(
            content=body,
            content_type=response_type.split(";", 1)[0],
            parse_mode="mineru-http",
            metadata={"adapter": "mineru-http", "source_filename": filename},
        )


def mineru_health(settings: Settings | None = None) -> dict[str, object]:
    try:
        return MinerUHttpAdapter(settings).health()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _multipart_form(
    boundary: str,
    *,
    fields: dict[str, str],
    list_fields: dict[str, list[str]],
    files: list[dict[str, object]],
) -> bytes:
    chunks: list[bytes] = []

    def add(value: str | bytes) -> None:
        chunks.append(value if isinstance(value, bytes) else value.encode("utf-8"))

    for name, value in fields.items():
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        add(f"{value}\r\n")
    for name, values in list_fields.items():
        for value in values:
            add(f"--{boundary}\r\n")
            add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
            add(f"{value}\r\n")
    for file_item in files:
        add(f"--{boundary}\r\n")
        add(
            "Content-Disposition: form-data; "
            f'name="{file_item["name"]}"; filename="{file_item["filename"]}"\r\n'
        )
        add(f"Content-Type: {file_item['content_type']}\r\n\r\n")
        add(file_item["content"])  # type: ignore[arg-type]
        add("\r\n")
    add(f"--{boundary}--\r\n")
    return b"".join(chunks)


def get_mineru_adapter(settings: Settings | None = None) -> MinerUAdapter:
    current = settings or get_settings()
    if current.mineru_use_fake or not current.mineru_endpoint:
        return FakeMinerUAdapter()
    return MinerUHttpAdapter(current)
