from nexus_app.crawler.quality_gate import evaluate_websearch_item


def _decision(**overrides):
    values = {
        "query": "电子商务产业(跨境电商和直播电商)政策和市场概况",
        "title": "跨境电商产业政策解读",
        "url": "https://example.gov.cn/policy/1",
        "content": "跨境电商产业政策和市场概况。" * 20,
        "rank_score": 0.9,
    }
    values.update(overrides)
    return evaluate_websearch_item(**values)


def test_websearch_quality_gate_rejects_low_rank_and_does_not_admit():
    decision = _decision(rank_score=0.01)
    assert decision.accepted is False
    assert decision.reason == "low_relevance"


def test_websearch_quality_gate_rejects_homepage_short_and_topic_mismatch():
    assert _decision(url="https://example.gov.cn/").reason == "homepage_or_channel"
    assert _decision(url="https://dzswgf.mofcom.gov.cn/m_gnxw/page9.html").reason == "homepage_or_channel"
    assert _decision(url="https://swj.weihai.gov.cn/col/col40666/index.html").reason == "homepage_or_channel"
    assert _decision(content="太短").reason == "too_short"
    assert _decision(title="财政预算", content="财政预算公开信息。" * 30).reason == "topic_coverage_insufficient"


def test_websearch_quality_gate_accepts_relevant_document():
    assert _decision().accepted is True


def test_websearch_quality_gate_rejects_news_reports():
    assert _decision(
        url="https://dzswgf.mofcom.gov.cn/news/phone/182/2026/3/m-1773899343396.html",
    ).reason == "news_report"
    assert _decision(title="行业动态", content="记者报道电子商务产业最新情况。" * 20).reason == "news_report"
