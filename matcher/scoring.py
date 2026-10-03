"""多因素加权打分器。

每个因素产出 (0-100 分, 理由列表)，理由全部携带证据片段，可回溯到
JD / 简历原文。某因素因 JD 未提供依据（如 JD 没写学历要求）时被禁用，
其基础权重按比例摊回其余启用因素，使不同 JD 的总分可比。
"""

from typing import Protocol

from .constants import (
    EDUCATION_ONE_LEVEL_BELOW,
    EDUCATION_TWO_OR_MORE_BELOW,
    EDUCATION_UNKNOWN_RESUME,
    EXPERIENCE_PENALTY_PER_YEAR,
    FACTOR_WEIGHTS,
    GRADE_THRESHOLDS,
    SEMANTIC_COSINE_CEILING,
    WEIGHT_REDISTRIBUTE,
)
from .models import Evidence, FactorScore, ParsedProfile, Reason


class SemanticScorer(Protocol):
    """语义打分的注入口：由 embeddings 模块提供实现，便于替换与测试。"""

    def score(self, jd_text: str, resume_text: str) -> float: ...

    @property
    def name(self) -> str: ...


def _required_skills_score(jd: ParsedProfile, resume: ParsedProfile) -> tuple[float, list[Reason], list[str]]:
    """硬性技能覆盖率。缺技能列出缺口；命中项逐条给出简历证据。"""
    required = jd.skill_names()
    if not required:
        return 0.0, [Reason(detail="JD 未解析出硬性技能要求", evidence=[])], []
    resume_hit = {s.name: s for s in resume.skills}
    matched = [s for s in required if s in resume_hit]
    missing = [s for s in required if s not in resume_hit]
    score = len(matched) / len(required) * 100.0

    reasons = [Reason(detail=f"硬性技能「{name}」在简历中命中", evidence=resume_hit[name].evidence) for name in matched]
    if missing:
        reasons.append(Reason(detail=f"硬性技能缺失：{'、'.join(missing)}", evidence=[]))
    return score, reasons, missing


def _preferred_skills_score(jd: ParsedProfile, resume: ParsedProfile) -> tuple[float | None, list[Reason]]:
    """加分项命中率。JD 无加分项分节时禁用（返回 None，权重摊回其余因素）。"""
    preferred = jd.preferred_skill_names()
    if not preferred:
        return None, []
    resume_hit = {s.name: s for s in resume.skills}
    matched = [s for s in preferred if s in resume_hit]
    missing = [s for s in preferred if s not in resume_hit]
    score = len(matched) / len(preferred) * 100.0

    reasons = [Reason(detail=f"加分技能「{name}」在简历中命中", evidence=resume_hit[name].evidence) for name in matched]
    if missing:
        reasons.append(
            Reason(
                detail=f"加分技能未命中：{'、'.join(missing)}（不作为硬性扣分主因，权重仅 "
                f"{FACTOR_WEIGHTS['preferred_skills']}）",
                evidence=[],
            )
        )
    return score, reasons


def _experience_score(jd: ParsedProfile, resume: ParsedProfile) -> tuple[float | None, list[Reason]]:
    """经验年限：达标满分；不足则每缺 1 年线性扣分；JD 未要求则禁用。"""
    need, got = jd.experience.years, resume.experience.years
    if need is None:
        return None, []
    if got is None:
        return 0.0, [
            Reason(
                detail=f"JD 要求约 {need:g} 年经验，简历未解析出年限",
                evidence=jd.experience.evidence,
            )
        ]
    if got >= need:
        return 100.0, [
            Reason(
                detail=f"简历年限 {got:g} 年满足 JD 要求的 {need:g} 年",
                evidence=jd.experience.evidence + resume.experience.evidence,
            )
        ]
    penalty = (need - got) * EXPERIENCE_PENALTY_PER_YEAR
    return max(0.0, 100.0 - penalty), [
        Reason(
            detail=f"简历年限 {got:g} 年低于 JD 要求 {need:g} 年，每缺 1 年扣 {EXPERIENCE_PENALTY_PER_YEAR:g} 分",
            evidence=jd.experience.evidence + resume.experience.evidence,
        )
    ]


def _education_score(jd: ParsedProfile, resume: ParsedProfile) -> tuple[float | None, list[Reason]]:
    """学历阶梯比较：低一级给部分分（经验可部分补偿），低两级以上给保底分。"""
    need, got = jd.education.rank, resume.education.rank
    if need is None:
        return None, []
    if got is None:
        return EDUCATION_UNKNOWN_RESUME, [
            Reason(
                detail=f"JD 要求{jd.education.level or ''}学历，简历未解析出学历",
                evidence=jd.education.evidence,
            )
        ]
    if got >= need:
        return 100.0, [
            Reason(
                detail=f"简历学历（{resume.education.level}）满足 JD 要求（{jd.education.level}）",
                evidence=jd.education.evidence + resume.education.evidence,
            )
        ]
    gap = need - got
    score = EDUCATION_ONE_LEVEL_BELOW if gap == 1 else EDUCATION_TWO_OR_MORE_BELOW
    note = "一级" if gap == 1 else "两级及以上"
    return score, [
        Reason(
            detail=f"简历学历（{resume.education.level}）低于 JD 要求（{jd.education.level}）{note}，"
            f"按固定档位计 {score:g} 分（无经验补偿机制）",
            evidence=jd.education.evidence + resume.education.evidence,
        )
    ]


def _domain_score(jd: ParsedProfile, resume: ParsedProfile) -> tuple[float | None, list[Reason]]:
    """领域重合率：JD 领域与简历领域的交集占比；JD 无领域则禁用。

    evidence 与 domains 同序（parser 保证），故按下标取对应领域的专属证据。
    """
    if not jd.domains.domains:
        return None, []
    jd_ev = dict(zip(jd.domains.domains, jd.domains.evidence, strict=False))
    resume_ev = dict(zip(resume.domains.domains, resume.domains.evidence, strict=False))
    overlap = sorted(set(jd.domains.domains) & set(resume.domains.domains))
    score = len(overlap) / len(jd.domains.domains) * 100.0

    reasons = []
    for d in overlap:
        evidence = [e for e in (resume_ev.get(d), jd_ev.get(d)) if e is not None]
        reasons.append(Reason(detail=f"领域「{d}」双方匹配", evidence=evidence))
    if not overlap:
        reasons.append(
            Reason(
                detail=f"JD 领域（{'、'.join(jd.domains.domains)}）与简历领域"
                f"（{'、'.join(resume.domains.domains) or '无'}）无交集",
                evidence=jd.domains.evidence,
            )
        )
    return score, reasons


def _semantic_score(scorer: SemanticScorer | None, jd_text: str, resume_text: str) -> tuple[float | None, list[Reason]]:
    """语义相似度兜底信号：捕获规则漏召回的同义表述。无 scorer 时禁用。"""
    if scorer is None:
        return None, []
    raw = scorer.score(jd_text, resume_text)
    mapped = max(0.0, min(1.0, raw / SEMANTIC_COSINE_CEILING)) * 100.0
    preview_len = min(60, len(jd_text))
    return mapped, [
        Reason(
            detail=f"全文语义相似度（{scorer.name}）：余弦 {raw:.3f}，"
            f"按上限 {SEMANTIC_COSINE_CEILING} 校准映射为 {mapped:.1f} 分",
            evidence=[Evidence(text=jd_text[:preview_len], start=0, end=preview_len, source="jd")],
        )
    ]


def compute_match(
    jd_text: str,
    resume_text: str,
    jd: ParsedProfile,
    resume: ParsedProfile,
    semantic_scorer: SemanticScorer | None = None,
) -> tuple[float, str, str, list[FactorScore], list[str]]:
    """计算总分、等级、逐因素得分。返回 (total, grade, grade_label, breakdown, missing_required)。"""
    req_score, req_reasons, missing_required = _required_skills_score(jd, resume)
    raw_scores: dict[str, tuple[float | None, list[Reason]]] = {
        "required_skills": (req_score, req_reasons),
        "preferred_skills": _preferred_skills_score(jd, resume),
        "experience": _experience_score(jd, resume),
        "education": _education_score(jd, resume),
        "domain": _domain_score(jd, resume),
        "semantic": _semantic_score(semantic_scorer, jd_text, resume_text),
    }

    active = {k: v for k, v in raw_scores.items() if v[0] is not None}
    base_total = sum(FACTOR_WEIGHTS[k] for k in active) or 1.0

    breakdown: list[FactorScore] = []
    total = 0.0
    for factor, (score, reasons) in raw_scores.items():
        base_w = FACTOR_WEIGHTS[factor]
        if score is None:
            breakdown.append(
                FactorScore(
                    factor=factor,
                    base_weight=base_w,
                    effective_weight=0.0,
                    score=0.0,
                    reasons=[Reason(detail="JD 未提供该因素依据，因素禁用，权重摊回其余因素", evidence=[])],
                    disabled=True,
                )
            )
            continue
        eff_w = base_w / base_total if WEIGHT_REDISTRIBUTE else base_w
        total += score * eff_w
        breakdown.append(
            FactorScore(
                factor=factor,
                base_weight=base_w,
                effective_weight=round(eff_w, 4),
                score=round(score, 1),
                reasons=reasons,
            )
        )

    for grade_floor, grade, label in GRADE_THRESHOLDS:
        if total >= grade_floor:
            return round(total, 1), grade, label, breakdown, missing_required
    return round(total, 1), "D", "不匹配", breakdown, missing_required  # pragma: no cover（阈值兜底）
