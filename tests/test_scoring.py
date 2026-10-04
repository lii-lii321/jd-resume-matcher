"""打分器测试：总分边界、权重重分配、理由证据可回溯。"""

import pytest

from matcher.constants import FACTOR_WEIGHTS
from matcher.parser import parse_profile
from matcher.scoring import compute_match, resolve_factor_weights

JD_FULL = """任职要求：
- 本科及以上学历；
- 3年以上 Python 后端经验；
- 熟练 FastAPI、MySQL。
"""

RESUME_FULL = """计算机专业硕士学历。
5年 Python 后端开发经验，熟练 FastAPI 与 MySQL。
"""


def _run(jd_text=JD_FULL, resume_text=RESUME_FULL, scorer=None, factor_weights=None):
    jd, resume = parse_profile(jd_text, "jd"), parse_profile(resume_text, "resume")
    return (
        compute_match(jd_text, resume_text, jd, resume, semantic_scorer=scorer, factor_weights=factor_weights),
        jd,
        resume,
    )


def test_perfect_match_scores_exact_100():
    # JD_FULL 的必须技能/经验/学历全部命中，其余因素禁用 -> 权重重分配后应为精确满分
    total = _run()[0][0]
    assert total == 100.0


def test_strong_resume_outranks_weak_resume():
    strong = _run()[0][0]
    weak = _run(resume_text="会一点 Excel 的运营，无学历信息")[0][0]
    assert strong > weak


def test_breakdown_has_all_factors():
    breakdown = _run()[0][3]
    assert {f.factor for f in breakdown} == {
        "required_skills",
        "preferred_skills",
        "experience",
        "education",
        "domain",
        "semantic",
    }


def test_weighted_scores_sum_to_total():
    result = _run()[0]
    total, breakdown = result[0], result[3]
    weighted_sum = sum(f.score * f.effective_weight for f in breakdown if not f.disabled)
    assert abs(total - weighted_sum) < 0.5  # 四舍五入容差


def test_effective_weights_sum_to_one_when_active():
    breakdown = _run()[0][3]
    active = [f for f in breakdown if not f.disabled]
    assert abs(sum(f.effective_weight for f in active) - 1.0) < 1e-6


def test_perfect_required_skills_scores_100():
    breakdown = _run()[0][3]
    required = next(f for f in breakdown if f.factor == "required_skills")
    assert required.score == 100.0


def test_missing_skill_reported_in_gap():
    result = _run(resume_text="本科，1年 Python 经验，只会 FastAPI")[0]
    assert "SQL" in result[4]  # 技能按规范名报告：JD 的 MySQL 归一为 SQL


# ---------- 自定义因素权重（resolve_factor_weights + compute_match 联动） ----------


def test_resolve_none_returns_builtin_mapping():
    assert resolve_factor_weights(None) is FACTOR_WEIGHTS


def test_resolve_merges_over_defaults_without_normalizing():
    weights = resolve_factor_weights({"experience": 0.5})
    assert weights["experience"] == 0.5
    assert weights["required_skills"] == FACTOR_WEIGHTS["required_skills"]  # 未提及保留默认
    assert abs(sum(weights.values()) - 1.3) < 1e-9  # 总和不强制为 1，摊回机制负责归一


def test_resolve_rejects_unknown_factor_and_bad_values():
    with pytest.raises(ValueError, match="未知因素名"):
        resolve_factor_weights({"salary": 0.5})
    with pytest.raises(ValueError, match="权重必须是正数"):
        resolve_factor_weights({"experience": 0.0})
    with pytest.raises(ValueError, match="权重必须是正数"):
        resolve_factor_weights({"experience": -0.1})
    with pytest.raises(ValueError, match="权重必须是正数"):
        resolve_factor_weights({"experience": True})  # bool 不是合法权重


def test_custom_weights_change_base_weight_and_stay_normalized():
    result, _, _ = _run(factor_weights={"experience": 0.5})
    total, breakdown = result[0], result[3]
    experience = next(f for f in breakdown if f.factor == "experience")
    assert experience.base_weight == 0.5
    active = [f for f in breakdown if not f.disabled]
    # effective_weight 按 4 位小数取整，非整除权重下求和有 ~1e-4 量级舍入偏差
    assert abs(sum(f.effective_weight for f in active) - 1.0) < 1e-3
    assert abs(total - sum(f.score * f.effective_weight for f in active)) < 0.5


def test_preferred_reason_cites_custom_weight():
    jd_text = "任职要求：Python。\n加分项：熟悉 Kubernetes。"
    result, _, _ = _run(jd_text=jd_text, resume_text="会 Python", factor_weights={"preferred_skills": 0.5})
    preferred = next(f for f in result[3] if f.factor == "preferred_skills")
    details = "；".join(r.detail for r in preferred.reasons)
    assert "权重仅 0.5" in details


def test_semantic_disabled_redistributes_weights():
    breakdown = _run(scorer=None)[0][3]
    semantic = next(f for f in breakdown if f.factor == "semantic")
    assert semantic.disabled and semantic.effective_weight == 0.0
    active = [f for f in breakdown if not f.disabled]
    assert abs(sum(f.effective_weight for f in active) - 1.0) < 1e-6


def test_jd_without_education_disables_factor():
    jd = "要求 3年 Python 经验，熟悉 FastAPI"
    breakdown = _run(jd_text=jd)[0][3]
    education = next(f for f in breakdown if f.factor == "education")
    assert education.disabled


def test_experience_partial_penalty():
    jd = "要求 5年 Python 经验"
    resume = "3年 Python 开发经验"
    breakdown = _run(jd_text=jd, resume_text=resume)[0][3]
    exp = next(f for f in breakdown if f.factor == "experience")
    assert exp.score == 50.0  # 缺 2 年 x 25 分


def test_education_one_level_below_partial_score():
    jd = "本科及以上学历"
    resume = "大专学历，符合岗位其他要求"
    breakdown = _run(jd_text=jd, resume_text=resume)[0][3]
    edu = next(f for f in breakdown if f.factor == "education")
    assert edu.score == 55.0


def test_every_reason_evidence_roundtrip():
    jd_text, resume_text = JD_FULL, RESUME_FULL
    result = _run()[0]
    for factor in result[3]:
        for reason in factor.reasons:
            assert reason.detail
            for ev in reason.evidence:
                source_text = jd_text if ev.source == "jd" else resume_text
                assert source_text[ev.start : ev.end] == ev.text, (
                    f"证据不可回溯: {ev.text!r} @ {ev.start}:{ev.end} in {ev.source}"
                )


def test_grade_thresholds():
    strong = _run()[0]  # 全匹配应达 A/B
    assert strong[1] in {"A", "B"}
    weak = _run(resume_text="会一点 Excel 的运营，无学历信息")[0]
    assert weak[1] in {"C", "D"}
