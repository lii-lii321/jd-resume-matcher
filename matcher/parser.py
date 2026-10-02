"""规则解析器：从 JD / 简历文本中抽取技能、学历、工作年限、领域。

纯规则 + 关键词，不依赖 LLM，离线可跑、结果确定。
所有抽取结果都带证据片段（原文偏移），供打分理由回溯。
"""

import re
from typing import Literal

from .models import DomainInfo, EducationInfo, Evidence, ExperienceInfo, ParsedProfile, SkillHit
from .taxonomy import DOMAIN_TAXONOMY, EDUCATION_LEVELS, SKILL_TAXONOMY, flatten_alias_map

# 工作年限的语境关键词：年限数字需出现在关键词附近才可信
_YEAR_CONTEXT_KEYWORDS = re.compile(r"经验|从业|工作|履历|exp|experience|work", re.IGNORECASE)
# 年限候选：阿拉伯数字或中文数字 + 年/years
_YEAR_CANDIDATE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?|[一二两三四五六七八九十]+)\s*(?:年|years?|yrs?)",
    re.IGNORECASE,
)
# 合理年限范围：超出视为年份（如"2020年"）误报并丢弃
_YEAR_MIN, _YEAR_MAX = 0.5, 50.0
_YEAR_CONTEXT_WINDOW = 12  # 年限数字与语境关键词的最大字符距离

_CN_NUMERALS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

_SKILL_ALIAS_MAP = flatten_alias_map(SKILL_TAXONOMY)
# 长别名优先，避免短别名抢占长别名的匹配区间
_SKILL_ALIASES_SORTED = sorted(_SKILL_ALIAS_MAP, key=len, reverse=True)

_MAJOR_PATTERN = re.compile(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z ]{1,12}?)(?:专业)")
_MAJOR_RELATED_PATTERN = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,10})(?:相关专业)")

# JD 加分项分节标记：首个命中的位置起，其后技能视为加分项而非必须项
_PREFERRED_SECTION_MARK = re.compile(
    r"加分项|优先条件|具备以下优先|nice\s*to\s*have|preferred(?:\s*skills)?|bonus",
    re.IGNORECASE,
)


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def _find_spans(text: str, alias: str) -> list[tuple[int, int]]:
    """返回别名在文本中的所有出现区间；ASCII 整词匹配，其余子串匹配。"""
    pattern = rf"\b{re.escape(alias)}\b" if _is_ascii(alias) else re.escape(alias)
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, re.IGNORECASE)]


def parse_skills(text: str, source: Literal["jd", "resume"]) -> list[SkillHit]:
    """抽取技能：按规范名去重；同一技能的多种写法都并入证据（每技能最多 3 条）。"""
    hits: dict[str, SkillHit] = {}
    claimed: list[tuple[int, int]] = []

    for alias in _SKILL_ALIASES_SORTED:
        canonical = _SKILL_ALIAS_MAP[alias]
        spans = [s for s in _find_spans(text, alias) if not any(s[0] < c[1] and c[0] < s[1] for c in claimed)]
        if not spans:
            continue
        claimed.extend(spans)
        new_evidence = [Evidence(text=text[a:b], start=a, end=b, source=source) for a, b in spans[:3]]
        if canonical in hits:
            hits[canonical].evidence = (hits[canonical].evidence + new_evidence)[:3]
        else:
            hits[canonical] = SkillHit(name=canonical, matched_alias=alias, evidence=new_evidence)

    return sorted(hits.values(), key=lambda h: h.name)


def parse_education(text: str, source: Literal["jd", "resume"]) -> EducationInfo:
    """抽取学历：取出现的最高学历；"及以上/以上" 只影响 JD 语义，解析层不做处理。"""
    best_rank, best_evidence = None, []
    for level in sorted(EDUCATION_LEVELS, key=lambda x: x["rank"], reverse=True):
        for alias in sorted(level["aliases"], key=len, reverse=True):
            spans = _find_spans(text, alias)
            if spans:
                best_rank = level["rank"]
                best_evidence = [Evidence(text=text[a:b], start=a, end=b, source=source) for a, b in spans[:2]]
                break
        if best_rank is not None:
            break

    major = None
    m = _MAJOR_RELATED_PATTERN.search(text) or _MAJOR_PATTERN.search(text)
    if m:
        major = m.group(1).strip()
    return EducationInfo(
        level=None if best_rank is None else next(l["name"] for l in EDUCATION_LEVELS if l["rank"] == best_rank),
        rank=best_rank,
        major=major,
        evidence=best_evidence,
    )


def _cn_numeral_to_float(num: str) -> float | None:
    if num.replace(".", "").isdigit():
        return float(num)
    if num in _CN_NUMERALS:
        return float(_CN_NUMERALS[num])
    if num == "十" or num.endswith("十"):  # 简单支持"十/二十"
        tens = _CN_NUMERALS.get(num[0], 1) if len(num) > 1 else 1
        return float(tens * 10 + (_CN_NUMERALS.get(num[-1], 0) if len(num) > 1 else 0))
    return None


def parse_experience(text: str, source: Literal["jd", "resume"]) -> ExperienceInfo:
    """抽取工作年限：优先取语境关键词（经验/工作/experience）附近的候选，均无则回退最大候选。

    超出 [0.5, 50] 区间的数字（如"2020年"的年份用法）直接丢弃，避免误报。
    """
    candidates: list[tuple[float, int, int]] = []
    for m in _YEAR_CANDIDATE.finditer(text):
        value = _cn_numeral_to_float(m.group("num"))
        if value is None or not (_YEAR_MIN <= value <= _YEAR_MAX):
            continue
        candidates.append((value, m.start(), m.end()))
    if not candidates:
        return ExperienceInfo()

    def near_context(span: tuple[float, int, int]) -> bool:
        window = text[max(0, span[1] - _YEAR_CONTEXT_WINDOW): span[2] + _YEAR_CONTEXT_WINDOW]
        return bool(_YEAR_CONTEXT_KEYWORDS.search(window))

    scoped = [c for c in candidates if near_context(c)]
    chosen = max(scoped or candidates, key=lambda c: c[0])
    return ExperienceInfo(
        years=chosen[0],
        evidence=[Evidence(text=text[chosen[1]:chosen[2]], start=chosen[1], end=chosen[2], source=source)],
    )


def parse_domains(text: str, source: Literal["jd", "resume"]) -> DomainInfo:
    """抽取领域标签：按规范名去重，保留证据。"""
    alias_map = flatten_alias_map(DOMAIN_TAXONOMY)
    domains: dict[str, Evidence] = {}
    for alias in sorted(alias_map, key=len, reverse=True):
        canonical = alias_map[alias]
        if canonical in domains:
            continue
        spans = _find_spans(text, alias)
        if spans:
            a, b = spans[0]
            domains[canonical] = Evidence(text=text[a:b], start=a, end=b, source=source)
    ordered = sorted(domains)
    return DomainInfo(
        domains=ordered,
        evidence=[domains[d] for d in ordered],
    )


def parse_profile(text: str, source: Literal["jd", "resume"]) -> ParsedProfile:
    """把一侧文本解析为结构化画像。JD 侧按加分项分节标记拆分必须/加分技能。"""
    if source == "jd":
        m = _PREFERRED_SECTION_MARK.search(text)
        if m:
            required_part, preferred_part = text[: m.start()], text[m.start():]
            required_hits = parse_skills(required_part, source)
            preferred_raw = parse_skills(preferred_part, source)
            required_names = {h.name for h in required_hits}
            preferred_hits = [h for h in preferred_raw if h.name not in required_names]
        else:
            required_hits, preferred_hits = parse_skills(text, source), []
        return ParsedProfile(
            skills=required_hits,
            preferred_skills=preferred_hits,
            education=parse_education(text, source),
            experience=parse_experience(text, source),
            domains=parse_domains(text, source),
        )

    return ParsedProfile(
        skills=parse_skills(text, source),
        education=parse_education(text, source),
        experience=parse_experience(text, source),
        domains=parse_domains(text, source),
    )
