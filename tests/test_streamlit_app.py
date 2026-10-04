"""Streamlit Demo（streamlit_app.py）的纯函数层测试：仅新增，不改任何现有测试。

不启动 Streamlit 服务，只验证模块可安全 import、纯函数在 examples/ 真实文件上的行为。
分数口径与 README「真实指标」一致：jd_backend × resume_strong = 88.0 / A 强烈推荐；
批量 chen_ming 84.6（B）> lin_xiaoyu 48.5（D）> wang_dalisheng 29.7（D）。
"""

import json
from pathlib import Path

import pytest

import streamlit_app as app
from matcher.batch import match_directory
from matcher.export import CSV_HEADER
from matcher.taxonomy import SKILL_TAXONOMY

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _REPO_ROOT / "examples"


def _example_pair() -> tuple[str, str]:
    return app.load_example_pair(_EXAMPLES)


def test_module_import_runs_no_ui_and_pure_helpers_exist():
    """import 即安全（无 st.* 顶层副作用），纯函数可被测试直接调用。"""
    assert callable(app.run_single_match)
    assert callable(app.run_batch_match)
    assert callable(app.weighted_contributions)
    assert callable(app.reason_rows)


def test_load_example_pair_matches_files_on_disk():
    jd, resume = _example_pair()
    assert jd == (_EXAMPLES / "jd_backend.md").read_text(encoding="utf-8")
    assert resume == (_EXAMPLES / "resume_strong.md").read_text(encoding="utf-8")
    assert jd.strip() and resume.strip()


def test_single_match_example_scores_in_readme_band():
    jd, resume = _example_pair()
    result = app.run_single_match(jd, resume)
    assert 80.0 <= result.total_score <= 95.0
    assert result.grade == "A" and result.grade_label == "强烈推荐"
    assert result.semantic_enabled and result.provider == "mock"


def test_single_match_breakdown_and_reasons_are_complete():
    jd, resume = _example_pair()
    result = app.run_single_match(jd, resume)

    assert len(result.score_breakdown) == 6  # 六因素一个不少
    assert any(f.reasons for f in result.score_breakdown)
    assert {f.factor for f in result.score_breakdown} == set(app.FACTOR_LABELS)

    # 贡献之和即总分（逐项 0.1 精度取整，6 项累计误差不超过 0.5）
    contributions = app.weighted_contributions(result)
    assert abs(sum(contributions.values()) - result.total_score) <= 0.5
    assert all(v >= 0.0 for v in contributions.values())

    rows = app.reason_rows(result)
    assert rows
    assert all(r["detail"] for r in rows)
    assert any(r["evidence"] for r in rows)  # 命中理由带证据片段
    for row in rows:
        for ev in row["evidence"]:
            assert ev["text"] and ev["end"] > ev["start"]
            assert ev["source"] in ("jd", "resume")


def test_single_match_semantic_toggle_changes_provider():
    jd, resume = _example_pair()
    off = app.run_single_match(jd, resume, use_semantic=False)
    assert off.semantic_enabled is False
    assert off.provider == "disabled"
    assert "semantic" in {f.factor for f in off.score_breakdown if f.disabled}


def test_factor_label_translates_known_and_keeps_unknown():
    assert app.factor_label("required_skills") == "必须技能"
    assert app.factor_label("unknown_factor") == "unknown_factor"


def test_batch_match_over_example_directory_reproduces_readme_ranking():
    jd, items = app.load_example_batch(_EXAMPLES)
    assert jd.strip()
    assert [name for name, _ in items] == [
        "chen_ming.md",
        "lin_xiaoyu.md",
        "wang_dalisheng.md",
    ]

    batch = app.run_batch_match(jd, items)
    assert (batch.total, batch.matched, batch.failed) == (3, 3, 0)
    scores = [e.result.total_score for e in batch.entries]
    assert scores == sorted(scores, reverse=True)
    assert batch.entries[0].resume_path == "chen_ming.md"
    assert 80.0 <= scores[0] <= 90.0 and batch.entries[0].result.grade == "B"

    rows = app.batch_rows(batch)
    assert len(rows) == 3
    assert rows[0]["名次"] == 1 and rows[0]["等级"].startswith("B")
    assert rows[0]["硬性技能缺口"] == "RESTful API"


def test_batch_match_records_empty_resume_as_error_row():
    jd, items = app.load_example_batch(_EXAMPLES)
    batch = app.run_batch_match(jd, items + [("empty.md", "   ")])
    assert (batch.matched, batch.failed) == (3, 1)
    last = batch.entries[-1]
    assert last.result is None and "文件为空" in (last.error or "")

    rows = app.batch_rows(batch)
    assert rows[-1]["错误"] and rows[-1]["名次"] == ""


def test_csv_bytes_is_utf8_sig_with_export_header():
    jd, items = app.load_example_batch(_EXAMPLES)
    batch = app.run_batch_match(jd, items)
    raw = app.csv_bytes(batch)
    assert raw.startswith(b"\xef\xbb\xbf")
    first_line = raw.decode("utf-8-sig").splitlines()[0]
    assert first_line == ",".join(CSV_HEADER)


def test_match_texts_and_match_directory_produce_identical_ranking(tmp_path):
    """重构回归：match_texts（内存文本）与 match_directory（目录）排序与分数一致。"""
    strong = "计算机专业硕士，5年 Python 后端经验。技能：Python、FastAPI、MySQL、Redis、Docker"
    weak = "计算机专业本科，1年 Python 使用经验。技能：Python"
    (tmp_path / "a_strong.md").write_text(strong, encoding="utf-8")
    (tmp_path / "b_weak.md").write_text(weak, encoding="utf-8")
    jd = "任职要求：3年以上 Python 后端经验，熟练 FastAPI、MySQL。"

    from_dir = match_directory(jd, tmp_path, use_semantic=False)
    from_texts = app.run_batch_match(jd, [("a_strong.md", strong), ("b_weak.md", weak)], use_semantic=False)

    assert [(e.resume_path, e.result.total_score) for e in from_dir.entries] == [
        (e.resume_path, e.result.total_score) for e in from_texts.entries
    ]
    assert (from_dir.total, from_dir.matched, from_dir.failed) == (
        from_texts.total,
        from_texts.matched,
        from_texts.failed,
    )


def test_load_example_batch_skips_unsupported_files():
    jd, items = app.load_example_batch(_EXAMPLES)
    assert jd.strip()
    assert all(name.endswith((".md", ".txt")) for name, _ in items)


def test_streamlit_app_renders_defaults_headlessly():
    """AppTest 无头渲染整页：示例预填直接产出理由/指标，脚本零异常（TTFS 冒烟）。"""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_REPO_ROOT / "streamlit_app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert len(at.text_area) >= 2  # 单份匹配页的 JD 与简历默认预填
    joined = "\n".join(md.value for md in at.markdown)
    assert "贡献" in joined  # 打分理由已带权重贡献渲染出来


# ---------- 自定义词表上传（parse_uploaded_vocab 纯函数 + 匹配联动） ----------


def test_parse_uploaded_vocab_none_returns_none():
    assert app.parse_uploaded_vocab(None) is None


def test_parse_uploaded_vocab_merges_user_entries_over_bundled():
    raw = json.dumps(
        {"schema_version": 1, "skills": {"Rust": ["rust"], "Python": ["py"]}},
        ensure_ascii=False,
    ).encode("utf-8")
    merged = app.parse_uploaded_vocab(raw)
    assert merged is not None
    assert merged["Rust"] == ["rust"]  # 新增
    assert merged["Python"] == ["py"]  # 用户条目覆盖内置
    assert merged["Java"] == SKILL_TAXONOMY["Java"]  # 未提及条目保留


def test_parse_uploaded_vocab_rejects_invalid_json_and_structure():
    with pytest.raises(ValueError):
        app.parse_uploaded_vocab(b"{not json")
    with pytest.raises(ValueError):
        app.parse_uploaded_vocab(json.dumps({"schema_version": 1}).encode("utf-8"))  # 缺 skills


def test_single_and_batch_match_honor_custom_vocab():
    rust_jd = "任职要求：3年以上 Rust 后端开发经验。"
    rust_resume = "5年 Rust 后端开发经验。"
    taxonomy = {**SKILL_TAXONOMY, "Rust": ["rust"]}

    single = app.run_single_match(rust_jd, rust_resume, use_semantic=False, skill_taxonomy=taxonomy)
    default = app.run_single_match(rust_jd, rust_resume, use_semantic=False)
    assert single.total_score == 100.0
    assert default.total_score < 50.0  # 默认词表不认识 Rust

    batch = app.run_batch_match(rust_jd, [("rust_dev.md", rust_resume)], use_semantic=False, skill_taxonomy=taxonomy)
    assert (batch.matched, batch.failed) == (1, 0)
    assert batch.entries[0].result.total_score == 100.0
