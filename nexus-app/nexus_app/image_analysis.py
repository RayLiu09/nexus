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

# Anti-chatter pre-amble shared by every prompt. Chinese LLMs default to
# "helpful assistant" mode and append blurbs like "说明：...", "如需...",
# "若需导出为 CSV、Markdown 或 Excel 格式...". This pre-amble plus the
# explicit forbidden-phrase list reduces those substantially; the response
# sanitisers in mineru_converter then enforce the contract as a safety net.
_STRICT_OCR_PREFIX = (
    "You are a strict OCR / transcription engine. Your only job is to "
    "transcribe the visible content of the image into the exact format "
    "requested. Do NOT explain, do NOT summarise, do NOT interpret, do NOT "
    "comment on the structure or aesthetics, do NOT mention alternative "
    "formats (CSV/Excel/etc.), do NOT offer further help. "
    "FORBIDDEN phrases (do not emit any of them, in any language): "
    "\"说明\", \"如需\", \"当然可以\", \"以下是\", \"若需\", \"可进一步\", "
    "\"可以为您\", \"如有需要\", \"Note:\", \"Summary:\", \"Overall\", "
    "\"In summary\", \"hope this helps\", \"let me know\", \"if you need\". "
    "After the last content line, end the response immediately. "
)

# Backwards-compatible alias (was named for table use first; same content).
_TABLE_PROMPT_PREFIX = _STRICT_OCR_PREFIX

_PROMPTS: dict[str, str] = {
    "image": (
        _STRICT_OCR_PREFIX
        + "This is a figure/diagram from a document. "
        "Caption: {caption}. "
        "Transcribe ONLY what is visible: text labels, annotations, formulas, "
        "numbers, and identifiers. Use a compact bullet list of the form "
        "\"- <label>: <value>\" or \"- <text>\". "
        "Do NOT prefix lines with \"Chart Type:\", \"Axis Labels:\", "
        "\"Legend:\", \"Key Data:\", \"Trend:\", \"Summary:\" or any other "
        "structural meta-label. "
        "If the image is actually a TABLE, output a GitHub-Flavoured Markdown "
        "table instead (header row → separator row '| --- | ... |' → data rows). "
        "If nothing readable is visible, respond with the single character '-' only."
    ),
    "chart": (
        _STRICT_OCR_PREFIX
        + "This is a chart/plot from a document. "
        "Caption: {caption}. "
        "Output ONLY the substantive content of the chart in this order, "
        "each part as a single block separated by one blank line, omitting "
        "any part that does not apply: \n"
        "(1) one short sentence stating axes and units (e.g. \"X 年份 2019-2024，"
        "Y 增速 0-60%\"); \n"
        "(2) a compact markdown table whose columns are the chart's series "
        "(legend entries) and whose rows are the data points read off the "
        "chart, OR a bullet list of \"- <label>: <value>\" pairs when the "
        "chart has no series. \n"
        "Do NOT prefix lines with \"Chart Type:\", \"Axis Labels:\", "
        "\"Legend Entries:\", \"Key Data Values:\", \"Trend:\", \"Summary:\", "
        "\"Note:\" or any other structural meta-label. "
        "Do NOT add a closing trend / summary / interpretation paragraph. "
        "If the chart is actually a TABLE (rows × columns of cells, no axes), "
        "output a GitHub-Flavoured Markdown table instead. "
        "If nothing is readable, respond with the single character '-' only."
    ),
    "table": (
        _STRICT_OCR_PREFIX
        + "This is a table from a technical document. "
        "Caption: {caption}. "
        "Output ONLY a GitHub-Flavoured Markdown table. "
        "Line 1 = header row '| col1 | col2 | ... |'. "
        "Line 2 = separator row '| --- | --- | ... |'. "
        "Each subsequent line = one data row '| v1 | v2 | ... |'. "
        "Every row MUST start with '|' and end with '|'. "
        "If a cell is unreadable use a single dash '-'. Do not invent values. "
        "If the visible content is empty, respond with the single character '-' only. "
        "Stop immediately after the final data row."
    ),
    "default": (
        _STRICT_OCR_PREFIX
        + "Caption: {caption}. "
        "Transcribe ONLY visible text, labels, numbers, and formulas."
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
            # Tables can easily exceed 1.5K tokens — bump generously so a
            # multi-row policy table is not truncated mid-cell.
            "max_tokens": 4000 if block_type == "table" else 1500,
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
