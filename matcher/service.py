"""服务层：把 解析 -> provider 构建 -> 打分 串成一条管线，供 API 与 CLI 共用。"""

from .embeddings import EmbeddingError, build_provider
from .models import MatchResult, ParsedProfile
from .parser import parse_profile
from .scoring import compute_match


def match_jd_resume(
    jd_text: str,
    resume_text: str,
    use_semantic: bool = True,
    provider_name: str = "mock",
    base_url: str | None = None,
    model: str | None = None,
    include_profiles: bool = True,
    skill_taxonomy: dict[str, list[str]] | None = None,
) -> MatchResult:
    """JD↔简历匹配主入口。openai_compatible 缺 key/URL 非法时自动降级，调用中失败时再降级为纯规则。

    skill_taxonomy 为 None 时用内置技能词表；传入自定义词表（如
    taxonomy.load_vocab(extra) 的合并结果）时双侧解析均按其匹配。
    """
    jd = parse_profile(jd_text, "jd", skill_taxonomy)
    resume = parse_profile(resume_text, "resume", skill_taxonomy)

    provider = None
    degraded_note = None
    if use_semantic:
        provider, degraded_note = build_provider(provider_name, base_url=base_url, model=model)

    try:
        total, grade, label, breakdown, missing = compute_match(
            jd_text, resume_text, jd, resume, semantic_scorer=provider
        )
    except EmbeddingError as exc:
        # 运行中失败（网络/配额）：降级为纯规则打分，语义因素禁用、权重摊回
        degraded_note = f"语义打分运行失败（{exc}），已降级为纯规则"
        total, grade, label, breakdown, missing = compute_match(jd_text, resume_text, jd, resume, semantic_scorer=None)
        provider = None

    return MatchResult(
        total_score=total,
        grade=grade,
        grade_label=label,
        score_breakdown=breakdown,
        missing_required_skills=missing,
        semantic_enabled=provider is not None,
        provider=provider.name if provider is not None else "disabled",
        degraded_note=degraded_note,
        jd_profile=jd if include_profiles else None,
        resume_profile=resume if include_profiles else None,
    )


def parse_only(text: str, source: str) -> ParsedProfile:
    """仅解析不打分（调试/单测辅助）。"""
    return parse_profile(text, "jd" if source == "jd" else "resume")
