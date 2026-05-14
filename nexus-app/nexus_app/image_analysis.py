"""Image content analysis via LiteLLM vision model.

Extracts meaningful content (text, data, formulas, diagrams) from images
produced by the MinerU parse stage. Used during normalize to populate the
`content` field of visual blocks in normalized_document.

Visual block types handled:
  - image  : architectural diagrams, figures → extract labels, structure
  - chart  : scatter/bar/line plots → extract axes, data, trends
  - table  : data tables → extract rows/columns as structured text
  - interline_equation : LaTeX already in spans, no VLM needed
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nexus_app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Vision model to use — must support image_url content parts via LiteLLM proxy
_VISION_MODEL = "dashscope/qwen3-omni-flash"

_PROMPTS: dict[str, str] = {
    "image": (
        "This is a figure/diagram from an academic or technical document. "
        "Caption: {caption}. "
        "Extract all meaningful content: labels, annotations, structural relationships, "
        "formulas, and key concepts shown. Be concise and precise."
    ),
    "chart": (
        "This is a chart/plot from a technical document. "
        "Caption: {caption}. "
        "Extract: chart type, axis labels and ranges, legend entries, "
        "key data values or trends. Be concise."
    ),
    "table": (
        "This is a table from a technical document. "
        "Caption: {caption}. "
        "Extract the full table content as structured text: column headers and all rows."
    ),
    "default": (
        "This image is from a technical document. "
        "Caption: {caption}. "
        "Extract all meaningful information: text, data, formulas, labels."
    ),
}


class ImageAnalyzer(Protocol):
    def analyze(
        self,
        image_bytes: bytes,
        block_type: str,
        caption: str = "",
    ) -> str | None:
        """Return extracted content string, or None if image should be skipped."""
        ...


class FakeImageAnalyzer:
    """Used in tests — returns a deterministic stub without calling any API."""

    def analyze(
        self,
        image_bytes: bytes,
        block_type: str,
        caption: str = "",
    ) -> str | None:
        return f"[fake-analysis: {block_type} block, {len(image_bytes)} bytes, caption={caption[:40]!r}]"


class LiteLLMImageAnalyzer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.litellm_endpoint:
            raise ValueError("LITELLM_ENDPOINT is not configured")

    def analyze(
        self,
        image_bytes: bytes,
        block_type: str,
        caption: str = "",
    ) -> str | None:
        prompt_template = _PROMPTS.get(block_type, _PROMPTS["default"])
        prompt = prompt_template.format(caption=caption or "not provided")

        img_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": _VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": 1500,
        }
        endpoint = self.settings.litellm_endpoint.rstrip("/")
        req = Request(
            f"{endpoint}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.settings.litellm_api_key or ''}",
                "Content-Type": "application/json",
            },
        )
        try:
            timeout = getattr(self.settings, "litellm_timeout", 60)
            with urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read())
            content = resp["choices"][0]["message"]["content"]
            return content.strip() if content and content.strip() else None
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("image_analysis failed for %s block: %s: %s", block_type, type(exc).__name__, exc)
            return None


def get_image_analyzer(settings: Settings | None = None) -> ImageAnalyzer:
    current = settings or get_settings()
    if not current.litellm_endpoint:
        return FakeImageAnalyzer()
    return LiteLLMImageAnalyzer(current)
