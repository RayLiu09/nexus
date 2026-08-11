from nexus_app.crawler.firecrawl_client import FirecrawlDocumentSnapshot
from nexus_app.crawler.quality_gate import (
    evaluate_snapshot,
    evaluate_websearch_item,
    normalized_content_fingerprint,
)


def _decision(**overrides):
    values = {
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


def test_websearch_quality_gate_rejects_homepage_and_short_content():
    assert _decision(url="https://example.gov.cn/").reason == "homepage_or_channel"
    assert _decision(url="https://dzswgf.mofcom.gov.cn/m_gnxw/page9.html").reason == "homepage_or_channel"
    assert _decision(url="https://swj.weihai.gov.cn/col/col40666/index.html").reason == "homepage_or_channel"
    assert _decision(content="太短").reason == "too_short"
    assert _decision(title="财政预算", content="财政预算公开信息。" * 30).accepted is True


def test_websearch_quality_gate_accepts_relevant_document():
    assert _decision().accepted is True


def test_websearch_quality_gate_rejects_news_reports():
    assert _decision(
        url="https://dzswgf.mofcom.gov.cn/news/phone/182/2026/3/m-1773899343396.html",
        title="某地举办电子商务交流活动",
        content="记者报道活动现场情况。" * 20,
    ).reason == "news_report"
    assert _decision(
        url="http://www.tibet.cn/cn/instant/domestic/202603/t20260325_7951590.html",
        title="前两月重点电商进口平台销售全球商品增长7.6%",
        content="前两月重点电商进口平台销售全球商品增长7.6%，市场运行保持平稳。" * 20,
    ).accepted is True
    assert _decision(title="行业动态", content="记者报道电子商务产业最新情况。" * 20).reason == "news_report"


def test_websearch_quality_gate_admits_policy_opinions_and_policy_news():
    policy_content = "浙江省进一步深化产教融合，明确职业教育、高等教育和产业协同发展的实施路径。" * 12

    assert _decision(
        title="浙江省人民政府办公厅关于进一步深化产教融合的实施意见",
        url="https://example.gov.cn/policy/industry-education-opinion",
        content=policy_content,
    ).accepted is True
    assert _decision(
        title="浙江出台进一步深化产教融合实施意见",
        url="https://example.gov.cn/news/industry-education-opinion",
        content=policy_content,
    ).accepted is True
    assert _decision(
        title="中国教育新闻网：浙江打出深化产教融合“组合拳”",
        url="https://example.edu.cn/news/industry-education-policy",
        content=policy_content,
    ).accepted is True


def test_firecrawl_quality_gate_rejects_low_value_activities_but_keeps_policy_notice():
    activity = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/news/activity",
        final_url="https://example.gov.cn/news/activity",
        title="电子商务培训活动通知",
        markdown="现将培训活动通知如下：请有关人员报名参加，活动现场安排另行通知。" * 4,
        html=None,
        metadata={},
    )
    policy = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/policy/opinion",
        final_url="https://example.gov.cn/policy/opinion",
        title="关于开展电子商务人才培训工作的通知",
        markdown="为贯彻落实相关政策，现制定实施方案。第一条明确培训工作要求和实施范围。" * 4,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(activity).reason == "low_value_activity"
    assert evaluate_snapshot(policy).accepted is True


def test_firecrawl_quality_gate_does_not_repeat_search_topic_matching():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/policy/overview",
        final_url="https://example.gov.cn/policy/overview",
        title="现代职业教育体系建设综述",
        markdown="该文讨论职业教育体系改革、产教融合与人才培养工作。" * 4,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).accepted is True


def test_firecrawl_content_fingerprint_ignores_html_markup_and_whitespace():
    html = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/a",
        final_url="https://example.gov.cn/a",
        title="政策",
        markdown=None,
        html="<article><h1>政策 文件</h1><p>支持 电子商务。</p></article>",
        metadata={},
    )
    markdown = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/b",
        final_url="https://example.gov.cn/b",
        title="政策",
        markdown="政策 文件\n\n支持 电子商务。",
        html=None,
        metadata={},
    )

    assert normalized_content_fingerprint(html) == normalized_content_fingerprint(markdown)
