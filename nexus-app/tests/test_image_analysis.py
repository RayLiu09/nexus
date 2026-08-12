from __future__ import annotations

import json

from nexus_app.config import Settings
from nexus_app.image_analysis import LiteLLMImageAnalyzer


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"{\\"rows\\":[]}"}}]}'


def test_visual_analysis_uses_default_governance_model_without_a_new_setting(monkeypatch):
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("nexus_app.image_analysis.urlopen", fake_urlopen)
    settings = Settings(
        LITELLM_ENDPOINT="http://litellm.test", LITELLM_API_KEY="test-key",
        DEFAULT_GOVERNANCE_MODEL="governance-default-model",
    )

    result = LiteLLMImageAnalyzer(settings).analyze(b"image", "talent_training_plan_table_structure", "岗位能力表")

    assert result == '{"rows":[]}'
    assert captured["payload"]["model"] == "governance-default-model"
    prompt = captured["payload"]["messages"][0]["content"][1]["text"]
    assert "Return exactly one JSON object" in prompt
    assert "no Markdown fence" in prompt
    assert "Required source rows" not in prompt
