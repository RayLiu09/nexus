from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from uuid import uuid4

from nexus_app.config import Settings, get_settings
from nexus_app.storage import checksum_value


def _select_backend(mime_type: str | None) -> str:
    """Map MIME type to MinerU v3 backend name.

    - text/html → pipeline  (HTML parser, no GPU needed)
    - default   → pipeline  (most compatible; vlm/hybrid are opt-in)
    """
    return "pipeline"


def _needs_ocr(mime_type: str | None) -> bool:
    """Return True when the content type warrants OCR activation."""
    if not mime_type:
        return False
    mt = mime_type.lower()
    return any(t in mt for t in ("image/", "application/pdf", "tiff"))


@dataclass(frozen=True)
class ParseResult:
    content: bytes          # mineru-result.json bytes
    content_type: str
    parse_mode: str
    metadata: dict[str, object]
    images: dict[str, bytes] = field(default_factory=dict)
    """Extracted images keyed by filename (e.g. 'page_0_img_0.png').

    Stored alongside the JSON result so downstream renderers can resolve
    image references without re-parsing the original document.
    """


class MinerUAdapter(Protocol):
    def parse(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        model_version: str | None = None,
    ) -> ParseResult:
        ...


class FakeMinerUAdapter:
    def parse(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        model_version: str | None = None,
    ) -> ParseResult:
        text = content.decode("utf-8", errors="ignore")
        title = filename.rsplit("/", 1)[-1]
        backend = model_version or _select_backend(content_type)
        result = {
            "schema_version": "mineru-fake-v1",
            "title": title,
            "markdown": f"# {title}\n\n{text[:4000]}",
            "content_checksum": checksum_value(content),
            "backend": backend,
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
            parse_mode=f"fake-{backend}",
            metadata={
                "adapter": "fake",
                "source_filename": title,
                "backend": backend,
                "ocr_enabled": _needs_ocr(content_type),
            },
            images={},
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

    def parse(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        model_version: str | None = None,
    ) -> ParseResult:
        # model_version kept for API compat; maps to MinerU v3 'backend' field
        backend = model_version or _select_backend(content_type)
        ocr_enabled = _needs_ocr(content_type)

        boundary = f"----nexus-mineru-{uuid4().hex}"
        form = _multipart_form(
            boundary,
            fields={
                "backend": backend,
                "parse_method": "auto",
                "formula_enable": "true",
                "table_enable": "true",
                "return_md": "true",
                "return_middle_json": "true",
                "return_model_output": "false",
                "return_content_list": "false",
                "return_images": "true",
                "response_format_zip": "true",
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
            response_type = (response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]

        return _unpack_mineru_response(
            body=body,
            response_type=response_type,
            filename=filename,
            effective_model=backend,
            ocr_enabled=ocr_enabled,
        )


def _unpack_mineru_response(
    body: bytes,
    response_type: str,
    filename: str,
    effective_model: str,
    ocr_enabled: bool,
) -> ParseResult:
    """Unpack MinerU response.

    When response_format_zip=true MinerU returns a ZIP archive containing:
      - <name>/<name>.json   (middle-json result)
      - <name>/images/       (extracted images, may be absent if none)
    When the response is plain JSON (no zip), treat it as the result directly.
    """
    images: dict[str, bytes] = {}
    result_json: bytes

    if "zip" in response_type or body[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                json_entries = [n for n in zf.namelist() if n.endswith(".json")]
                image_entries = [
                    n for n in zf.namelist()
                    if not n.endswith(".json") and not n.endswith("/")
                    and any(n.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".bmp"))
                ]
                if not json_entries:
                    result_json = body
                else:
                    result_json = zf.read(json_entries[0])
                for img_path in image_entries:
                    img_name = img_path.rsplit("/", 1)[-1]
                    images[img_name] = zf.read(img_path)
        except zipfile.BadZipFile:
            result_json = body
    else:
        result_json = body

    return ParseResult(
        content=result_json,
        content_type="application/json",
        parse_mode=f"mineru-http-{effective_model}",
        metadata={
            "adapter": "mineru-http",
            "source_filename": filename,
            "model_version": effective_model,
            "ocr_enabled": ocr_enabled,
            "image_count": len(images),
        },
        images=images,
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
