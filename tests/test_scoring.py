"""打分器测试：总分边界、权重重分配、理由证据可回溯。"""

from matcher.parser import parse_profile
from matcher.scoring import compute_match

JD_FULL = """任职要求：
- 本科及以上学历；
- 3年以上 Python 后端经验；
- 熟练 FastAPI、MySQL。
"""

RESUME_FULL = """计算机专业硕士学历。
5年 Python 后端开发经验，熟练 FastAPI 与 MySQL。
"""


def _run(jd_text=JD_FULL, resume_text=RESUME_FULL, scorer=None):
    jd, resume = parse_profile(jd_text, "jd"), parse_profile(resume_text, "resume")
    return compute_match(jd_text, resume_text, jd, resume, semantic_scorer=scorer), jd, resume


def test_total_score_within_bounds():
    (total, *_rest) = _run()[0]
    assert 0.0 <= total <= 100.0


def test_breakdown_has_all_factors():
    breakdown = _run()[0][3]
    assert {f.factor for f in breakdown} == {
        "required_skills", "preferred_skills", "experience", "education", "domain", "semantic",
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
                assert source_text[ev.start:ev.end] == ev.text, (
                    f"证据不可回溯: {ev.text!r} @ {ev.start}:{ev.end} in {ev.source}"
                )


def test_grade_thresholds():
    strong = _run()[0]           # 全匹配应达 A/B
    assert strong[1] in {"A", "B"}
    weak = _run(resume_text="会一点 Excel 的运营，无学历信息")[0]
    assert weak[1] in {"C", "D"}
