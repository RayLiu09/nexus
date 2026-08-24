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
    }
    values.update(overrides)
    return evaluate_websearch_item(**values)


def test_websearch_quality_gate_does_not_repeat_provider_relevance_ranking():
    assert _decision().accepted is True


def test_websearch_quality_gate_rejects_homepage_and_short_content():
    assert _decision(url="https://example.gov.cn/").reason == "homepage_or_channel"
    assert _decision(url="https://dzswgf.mofcom.gov.cn/m_gnxw/page9.html").reason == "homepage_or_channel"
    assert _decision(url="https://swj.weihai.gov.cn/col/col40666/index.html").reason == "homepage_or_channel"
    assert _decision(content="太短").reason == "too_short"
    assert _decision(title="财政预算", content="财政预算公开信息。" * 30).accepted is True


def test_websearch_quality_gate_accepts_usable_document():
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
        markdown="为贯彻落实相关政策，现制定实施方案。第一条明确培训工作要求和实施范围。" * 10,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(activity).reason == "low_value_activity"
    assert evaluate_snapshot(policy).accepted is True


def test_firecrawl_quality_gate_rejects_training_event_recap_despite_generic_industry_terms():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://www.example.com/information/id/250",
        final_url="https://www.example.com/information/id/250",
        title="新闻资讯",
        markdown=(
            "2023年中泰合作电子商务项目精英培训班在当地开班。"
            "本次培训由多家机构联合主办，参培学员65人，课程包含电子商务产业发展、"
            "电商平台运营和网络营销等内容，结业后颁发结业证书。"
        ) * 4,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "low_value_activity"


def test_firecrawl_quality_gate_keeps_activity_report_with_statistical_evidence():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/news/market-report",
        final_url="https://example.gov.cn/news/market-report",
        title="电子商务市场运行报告发布",
        markdown=(
            "发布会上公布统计数据：本季度网络零售额同比增长12%，"
            "并说明了数据来源、统计口径和市场运行情况。"
        ) * 10,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).accepted is True


def test_firecrawl_quality_gate_rejects_signing_and_unveiling_event_recap():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://example.com/information/academy-unveiling",
        final_url="https://example.com/information/academy-unveiling",
        title="某职业学院数字商务产业学院揭牌成立",
        markdown=(
            "学院与企业举行签约揭牌仪式，多位嘉宾出席并分别致辞。"
            "双方将共同探索产教融合新路径，为行业培养高素质技术技能人才。"
        ) * 5,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "low_value_activity"


def test_firecrawl_quality_gate_rejects_human_interest_person_profile():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://www.news.example.cn/person/1",
        final_url="https://www.news.example.cn/person/1",
        title="胡菊玲：奋力向前的农产品电商追梦人",
        markdown=(
            "胡菊玲经营当地农产品电商企业，带领团队开展选品和直播运营。"
            "她计划继续拓展产品品类并提升用户体验。（完）"
        ) * 5,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "low_value_person_profile"


def test_firecrawl_quality_gate_does_not_repeat_search_topic_matching():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/policy/overview",
        final_url="https://example.gov.cn/policy/overview",
        title="现代职业教育体系建设综述",
        markdown="该文讨论职业教育体系改革、产教融合与人才培养工作。" * 15,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).accepted is True


def test_firecrawl_quality_gate_rejects_low_content_page_without_topic_matching():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://career.example.edu.cn/company/123",
        final_url="https://career.example.edu.cn/company/123",
        title="高校就业资讯网",
        markdown=(
            "某中学为公办完全中学，位于北京市海淀区。学校推进课程改革，"
            "探索选课走班育人模式，创造适合每位学生发展的教育。"
        ) * 2,
        html=None,
        metadata={},
    )

    assert len(snapshot.text_for_quality.strip()) < 300
    assert evaluate_snapshot(snapshot).reason == "too_short"


def test_firecrawl_quality_gate_keeps_public_document_with_login_navigation():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://www.hengyang.gov.cn/xxgk/dtxx/tzgg/gsgg/20211103/i2528111.html",
        final_url="https://www.hengyang.gov.cn/xxgk/dtxx/tzgg/gsgg/20211103/i2528111.html",
        title="衡阳市推进职业教育现代化实施方案",
        markdown=(
            "[中国政府网](http://www.gov.cn/) [用户登录](https://auth.example.gov.cn/user/login)\n\n"
            "《衡阳市推进职业教育现代化服务“三高四新”实施方案》\n"
            "为推进现代职业教育高质量发展，现制定本实施方案。第一条明确工作目标和任务。"
        ) * 6,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).accepted is True


def test_firecrawl_quality_gate_rejects_access_wall_and_captcha_challenge():
    login_wall = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/restricted",
        final_url="https://example.gov.cn/restricted",
        title="受限页面",
        markdown="请登录后查看完整内容。请输入账号和密码登录。" * 4,
        html=None,
        metadata={},
    )
    captcha_wall = FirecrawlDocumentSnapshot(
        source_url="https://example.gov.cn/challenge",
        final_url="https://example.gov.cn/challenge",
        title="安全验证",
        markdown="安全验证：请输入验证码后继续访问。" * 5,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(login_wall).reason == "login_or_captcha"
    assert evaluate_snapshot(captcha_wall).reason == "login_or_captcha"


def test_firecrawl_quality_gate_rejects_github_blob_session_shell():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://github.com/example/project/blob/main/words.txt",
        final_url="https://github.com/example/project/blob/main/words.txt",
        title="words.txt",
        markdown=(
            "You signed in with another tab or window. Reload to refresh your session.\n"
            "You signed out in another tab or window. Reload to refresh your session.\n"
            "You switched accounts on another tab or window. Reload to refresh your session."
        ),
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "github_blob_page_shell"


def test_firecrawl_quality_gate_rejects_github_blob_source_file():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://github.com/microsoft/Windows-classic-samples/blob/main/Samples/IME/cpp/SampleIME/Dictionary/SampleIMESimplifiedQuanPin.txt",
        final_url="https://github.com/microsoft/Windows-classic-samples/blob/main/Samples/IME/cpp/SampleIME/Dictionary/SampleIMESimplifiedQuanPin.txt",
        title="SampleIMESimplifiedQuanPin.txt",
        markdown=(
            "# SampleIMESimplifiedQuanPin.txt\n\n"
            "Copy path More file actions\n\n"
            "54635 lines (54635 loc) · 1.5 MB\n\n"
            "a 阿\n"
            "ai 爱\n"
        ),
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "github_blob_source_file"


def test_firecrawl_quality_gate_keeps_substantive_github_document():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://github.com/example/project/blob/main/readme.md",
        final_url="https://github.com/example/project/blob/main/readme.md",
        title="README",
        markdown=(
            "# 项目说明\n\n"
            "本项目提供企业数据资产平台的建设方案与实施路径。"
            "方案覆盖数据接入、标准化治理与检索服务等关键能力。"
        ) * 6,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).accepted is True


def test_firecrawl_quality_gate_rejects_non_chinese_content():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://nationaltoday.com/",
        final_url="https://nationaltoday.com/",
        title="National Today",
        markdown=(
            "National Today is the home of fun, unusual holidays. "
            "We track thousands of national days, weeks and months."
        ) * 4,
        html=None,
        metadata={},
    )

    assert evaluate_snapshot(snapshot).reason == "non_chinese_content"


def test_firecrawl_quality_gate_keeps_chinese_document_with_latin_terms():
    snapshot = FirecrawlDocumentSnapshot(
        source_url="https://www.nda.gov.cn/sjj/swdt/dfdt/0624/20250624194955998636402_pc.html",
        final_url="https://www.nda.gov.cn/sjj/swdt/dfdt/0624/20250624194955998636402_pc.html",
        title="地方动态 | 云南省数据局关于印发《2025年数字云南建设工作要点》等四个工作要点的通知",
        markdown=(
            "云南省数据局印发2025年数字云南建设工作要点，围绕AI、5G、"
            "大数据等新质生产力方向推进数字贸易与跨境数据流动。"
        ) * 6,
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
