"""解析器测试：技能/学历/年限/领域抽取与证据偏移。"""

from matcher.parser import parse_domains, parse_education, parse_experience, parse_profile, parse_skills


def test_skills_english_extraction():
    hits = {h.name for h in parse_skills("熟练使用 Python 和 MySQL，了解 Docker", "resume")}
    assert {"Python", "SQL", "Docker"} <= hits


def test_skills_alias_maps_to_canonical():
    hits = {h.name: h for h in parse_skills("用过 mysql 和 k8s", "resume")}
    assert "SQL" in hits and "Kubernetes" in hits
    assert hits["SQL"].matched_alias == "mysql"


def test_skills_ascii_word_boundary():
    # "easyexcel" 不应命中 "excel"（整词边界）
    assert parse_skills("擅长 easyexcel", "resume") == []


def test_skills_cjk_substring_match():
    # 中文词没有 \\b 边界，需按子串命中
    hits = {h.name for h in parse_skills("会机器学习的候选人优先", "resume")}
    assert "机器学习" in hits


def test_skills_go_alias_without_space():
    # 回归：『熟悉go语言』『熟悉 go 语言』均应命中 Go（原别名带前导空格导致漏检）
    assert "Go" in {h.name for h in parse_skills("熟悉go语言", "resume")}
    assert "Go" in {h.name for h in parse_skills("熟悉 go 语言", "resume")}
    assert "Go" in {h.name for h in parse_skills("写过 golang", "resume")}


def test_skills_dedupe_by_canonical():
    hits = parse_skills("熟悉 JavaScript，写 js 很快", "resume")
    js_hits = [h for h in hits if h.name == "JavaScript"]
    assert len(js_hits) == 1
    assert len(js_hits[0].evidence) == 2  # 两种写法各留一条证据


def test_skills_evidence_spans_roundtrip():
    text = "使用 Python 和 FastAPI"
    for hit in parse_skills(text, "resume"):
        for ev in hit.evidence:
            assert ev.source == "resume"
            assert text[ev.start:ev.end] == ev.text


def test_education_rank_and_major():
    info = parse_education("计算机科学与技术专业，硕士学历", "resume")
    assert info.rank == 2
    assert info.level == "硕士"
    assert info.major == "计算机科学与技术"


def test_education_takes_highest_rank():
    assert parse_education("本科学历，后取得硕士学位", "resume").rank == 2


def test_education_missing_returns_none():
    info = parse_education("自学者，无学历", "resume")
    assert info.rank is None and info.evidence == []


def test_years_with_context_keyword():
    info = parse_experience("拥有 5年 Python 开发经验", "resume")
    assert info.years == 5.0
    assert info.evidence[0].text == "5年"


def test_years_rejects_calendar_year():
    assert parse_experience("2020年毕业", "resume").years is None
    assert parse_experience("2020年毕业，3年工作经验", "resume").years == 3.0


def test_years_chinese_numeral():
    assert parse_experience("三年工作经验", "resume").years == 3.0


def test_years_chinese_numeral_compound():
    # 覆盖 十X / X十 / X十Y 全形态（回归：二十年曾被算成 30）
    assert parse_experience("十年工作经验", "resume").years == 10.0
    assert parse_experience("十五年工作经验", "resume").years == 15.0
    assert parse_experience("二十年工作经验", "resume").years == 20.0
    assert parse_experience("二十五年工作经验", "resume").years == 25.0


def test_years_missing_returns_none():
    info = parse_experience("刚毕业的学生", "resume")
    assert info.years is None and info.evidence == []


def test_domains_extraction():
    info = parse_domains("有金融、电商领域经验", "resume")
    assert {"金融", "电商"} <= set(info.domains)
    assert len(info.evidence) == len(info.domains)


def test_jd_preferred_section_split():
    jd = parse_profile(
        "任职要求：3年 Python 经验，熟悉 FastAPI。\n加分项：熟悉 Kafka。", "jd"
    )
    assert {"Python", "FastAPI"} <= set(jd.skill_names())
    assert set(jd.preferred_skill_names()) == {"Kafka"}


def test_jd_without_preferred_section_all_required():
    jd = parse_profile("要求熟悉 Python 与 Redis", "jd")
    assert set(jd.skill_names()) == {"Python", "Redis"}
    assert jd.preferred_skills == []


def test_empty_text_parse_no_crash():
    p = parse_profile("", "jd")
    assert p.skills == [] and p.education.rank is None and p.experience.years is None
