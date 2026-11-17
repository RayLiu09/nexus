"""Conservative display-title cleaning, independent of occupation normalization."""

from __future__ import annotations

import re
import unicodedata


TITLE_CLEANING_VERSION = "simple-v2"
_AD = r"(?:急聘|诚聘|高薪急聘|高薪诚聘|高薪招聘|招聘|直招|急招|热招)"
_BRACKETED_AD = re.compile(rf"(?:【\s*{_AD}\s*】|\[\s*{_AD}\s*\]|\(\s*{_AD}\s*\))")
_PREFIX_AD = re.compile(rf"^{_AD}(?:\s*[:：|·-]\s*|\s+)")
_JOB_ID_SUFFIX = re.compile(
    r"\s*[\[(【]\s*(?:(?:MJ|JR|JD|J)\d{4,}|职位(?:编号|ID)\s*[:：]?\s*[A-Z0-9_-]+)\s*[\])】]\s*$",
    re.IGNORECASE,
)
_SALARY_SUFFIX = re.compile(
    r"\s+(?:\d+(?:\.\d+)?\s*[-~至]\s*)?\d+(?:\.\d+)?\s*(?:[kK]|千|万)"
    r"(?:元)?(?:[/·](?:月|年))?(?:[·•]\d+薪)?\s*$"
)
_AMOUNT = r"\d+(?:\.\d+)?(?:\s*[-~至]\s*\d+(?:\.\d+)?)?\s*(?:[kKwW]|千|万|元)"
_PAY = re.compile(
    rf"(?:(?:无责(?:任)?|综合|转正)?(?:底薪|薪资|薪酬)|保底|月收入|月入|月薪|年薪|无责(?:任)?)"
    rf"\s*(?:{_AMOUNT}|\d{{3,}}|[一二三四五六七八九十]+[千万元]|面议)(?:起|以上)?\+?"
    rf"|(?:薪资|薪酬|工资)面议|高薪(?:大平台|坐班)?|高底薪|无责底薪"
    rf"|(?:高|绩效|长期|有)?(?:提成|佣金|奖金)(?!核算|结算|管理|制度|设计|系统|专员)"
    rf"|年终(?:奖|分红)?|\d{{2}}薪"
)
_BENEFITS = re.compile(
    r"签正规劳动合同买[五六七5-7]险(?:[一二三123]金)?"
    r"|(?:入职)?(?:缴纳|提供|购买|买|含)?[五六七5-7]险(?:[一二三123]金)?"
    r"|(?:周末)?双休(?:不加班|法休)?|周末休息|单双休|大小周|有双休|弹性双休|法休"
    r"|(?:朝|早)[九9]晚[五六七567]|不加班"
    r"|包吃(?:包住|住)?|包食宿|包住宿|包住|(?:可)?(?:免费|提供)住宿(?:等)?"
    r"|(?:交通|餐饮|餐费|住房|通讯|夜班|高温|车|饭)补贴|带薪(?:培训|年假|休假)"
    r"|地铁直达|地铁口|近地铁|(?:就近)(?:安排|分配)"
    r"|准时下班|试用期不打折|每天\d+小时|稳定岗"
)
_ACCEPTANCE = re.compile(
    r"(?:接受|可接受|可招|可接收)(?:实习生?|应届生?|无经验|小白)"
    r"|可实习|可兼职|不会可教|可培养|带教|多职级招聘|岗位招聘信息"
)
_WORK_MODE = re.compile(
    r"(?:可)?(?:线上)?远程(?:办公|协作)(?!系统|平台|软件|产品|技术)"
    r"|(?:可)?居家(?:远程)?办公|全国可做"
)
_BRACKETS = re.compile(r"\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")
_TIME = re.compile(r"\d{1,2}:\d{2}\s*[-~至]\s*\d{1,2}:\d{2}")
_DELIMITERS = " \t+-—|｜·•,，、;；/!！:："
_STANDALONE_SALARY = re.compile(
    rf"(?:{_AMOUNT})(?:\s*[-~至]\s*{_AMOUNT})?(?:元)?(?:[/·](?:月|年))?(?:起|以上)?\+?",
    re.IGNORECASE,
)
_BRACKET_NOISE = re.compile(
    r"(?:(?:无责(?:任)?|固定|浮动|高|带|保底|无)?底薪(?:高|加|资)?|永久无责|无责(?:任)?|高提|补助|绩效奖)"
    r"|\d{3,}(?:底薪)|地铁(?:旁)?|多网点可就近"
    r"|[^()]{0,20}地铁站旁(?:\d+米左右)?|提供意向客户|提供准客户资源"
    r"|(?:必须有|需有|要求有)[^()]{1,30}经验|不限经验|接受小白"
    rf"|{_AMOUNT}底薪|保底薪资|高激励|合伙人计划|\.?地铁旁"
)


def is_detail_block_title(title: str) -> bool:
    """Identify salary-first source detail blocks, never invent a missing title."""
    text = unicodedata.normalize("NFKC", title).strip()
    return bool(
        re.match(rf"^{_AMOUNT}", text)
        and re.search(r"(?:有限公司|有限责任公司|集团|公司)", text)
        and re.search(r"(?:本科|大专|中专|硕士|博士|\d+-\d+年)", text)
    )


def _remove_explicit_noise(text: str) -> str:
    text = _PAY.sub("", text)
    text = _BENEFITS.sub("", text)
    text = _ACCEPTANCE.sub("", text)
    return _WORK_MODE.sub("", text)


def _trim_decorations(text: str) -> str:
    text = text.strip(_DELIMITERS.replace("+", ""))
    if not text.lower().endswith("c++"):
        text = text.rstrip("+").rstrip()
    return text.lstrip("+").lstrip()


def _clean_bracket(match: re.Match) -> str:
    original = match.group()
    inner = original[1:-1]
    if inner.strip() in {"远程", "居家办公", "线上远程协作"}:
        return ""
    parts = re.split(r"[·•,，、;；|/]+|(?<!\+)\+(?!\+)", inner)
    cleaned_parts = []
    changed = False
    for part in parts:
        cleaned = _remove_explicit_noise(part)
        if (_TIME.fullmatch(cleaned.strip()) or _STANDALONE_SALARY.fullmatch(cleaned.strip())
                or _BRACKET_NOISE.fullmatch(cleaned.strip())):
            cleaned = ""
        changed |= cleaned != part
        cleaned = _trim_decorations(cleaned) if changed else cleaned.strip()
        if cleaned:
            cleaned_parts.append(cleaned)
    if not changed:
        return original
    if not cleaned_parts:
        return ""
    return original[0] + "/".join(cleaned_parts) + original[-1]


def clean_job_title(title: str) -> str:
    """Remove explicit noise without dropping specialty, rank or semantic brackets.

    Never infer a canonical occupation, remove geographic names, split compound
    jobs or replace technical terms. A noise-only title falls back to its basic
    text-normalized value rather than producing an empty display title.
    """
    text = unicodedata.normalize("NFKC", title)
    text = "".join(
        " " if char.isspace() else char
        for char in text
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf"}
    )
    text = " ".join(text.split())
    if is_detail_block_title(text):
        return text or title
    cleaned = text
    while True:
        previous = cleaned
        cleaned = _BRACKETED_AD.sub("", cleaned)
        cleaned = _BRACKETS.sub(_clean_bracket, cleaned)
        cleaned = _PREFIX_AD.sub("", cleaned.strip())
        # These prefixes are explicit advertisements, unlike 招聘专员/招聘经理.
        cleaned = re.sub(r"^(?:急聘|诚聘|急招|热招|高薪招聘|高薪诚聘)[:：\s]*", "", cleaned)
        cleaned = re.sub(r"^招聘(?!专员|经理|主管|顾问|助理|总监|负责人|运营|管理|培训)(?=.{3,})", "", cleaned)
        cleaned = _remove_explicit_noise(cleaned)
        cleaned = _JOB_ID_SUFFIX.sub("", cleaned)
        cleaned = _SALARY_SUFFIX.sub("", cleaned)
        cleaned = _TIME.sub("", cleaned)
        # Whole salary tokens and trailing attached ranges are decorations;
        # technical names such as 8K视频工程师 and 3D设计师 remain untouched.
        cleaned = re.sub(r"\d+(?:\.\d+)?[kKwW]?[-~至]\d+(?:\.\d+)?[kKwW](?:起|以上)?$", "", cleaned)
        cleaned = re.sub(rf"(?<![\w.]){_AMOUNT}(?:起|以上)?(?=$|[\s+|·/])", "", cleaned)
        cleaned = re.sub(r"(?<=[师员理管])\d{4,}(?:元)?\+?$", "", cleaned)
        cleaned = re.sub(r"^\d{4,6}\+", "", cleaned)
        cleaned = re.sub(r"\s+\d{1,3}人$", "", cleaned)
        cleaned = re.sub(r"(?<=[+|/])(?:晋升|互联网大厂)(?=$|[+|/])", "", cleaned)
        cleaned = re.sub(r"(?<![A-Za-z0-9])-{2,}(?![A-Za-z0-9])", "-", cleaned)
        cleaned = re.sub(r"\s*[|·•,，、;；]\s*(?=[|·•,，、;；]|$)", "", cleaned)
        cleaned = _trim_decorations(cleaned)
        cleaned = " ".join(cleaned.split())
        if cleaned == previous:
            return cleaned or text or title
