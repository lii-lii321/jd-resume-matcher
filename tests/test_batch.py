"""批量匹配测试：排序、容错（空文件/超限/坏扩展名）、目录语义与 JSON 可序列化。"""

import pytest

from matcher import batch as batch_mod
from matcher.batch import match_directory

_JD = (
    "任职要求：本科及以上学历，3年以上 Python 后端开发经验，"
    "熟练使用 FastAPI、MySQL、Redis；熟悉 Docker。加分项：熟悉 Kafka。"
)

_RESUME_STRONG = """# 强简历
计算机专业硕士，5年 Python 后端经验。
技能：Python、FastAPI、MySQL、Redis、Docker、Kafka
"""

_RESUME_WEAK = """# 弱简历
计算机专业本科，1年 Python 使用经验。技能：Python
"""


@pytest.fixture()
def resume_dir(tmp_path):
    d = tmp_path / "resumes"
    d.mkdir()
    (d / "a_strong.md").write_text(_RESUME_STRONG, encoding="utf-8")
    (d / "b_weak.md").write_text(_RESUME_WEAK, encoding="utf-8")
    return d


def test_batch_ranks_matched_by_score_desc(resume_dir):
    result = match_directory(_JD, resume_dir)
    assert (result.total, result.matched, result.failed) == (2, 2, 0)
    scores = [e.result.total_score for e in result.entries]
    assert scores == sorted(scores, reverse=True)
    assert result.entries[0].resume_path == "a_strong.md"
    assert result.entries[0].result.grade in ("A", "B")


def test_batch_entry_fields_and_missing_skills(resume_dir):
    result = match_directory(_JD, resume_dir)
    weak = next(e for e in result.entries if e.resume_path == "b_weak.md")
    assert weak.error is None
    assert weak.result.missing_required_skills  # 弱简历必有硬性缺口
    assert weak.result.jd_profile is None  # 批量默认不带画像


def test_batch_failed_entries_sorted_last(resume_dir):
    (resume_dir / "c_empty.md").write_text("", encoding="utf-8")
    result = match_directory(_JD, resume_dir)
    assert (result.total, result.matched, result.failed) == (3, 2, 1)
    assert all(e.result is not None for e in result.entries[:2])
    failed = result.entries[-1]
    assert failed.result is None and failed.error is not None
    assert "a_strong.md" in [e.resume_path for e in result.entries[:2]]


def test_batch_ignores_unsupported_extensions_and_subdirs(resume_dir):
    (resume_dir / "note.docx").write_text(_RESUME_STRONG, encoding="utf-8")
    sub = resume_dir / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text(_RESUME_WEAK, encoding="utf-8")
    result = match_directory(_JD, resume_dir)
    assert {e.resume_path for e in result.entries} == {"a_strong.md", "b_weak.md"}


def test_batch_txt_extension_supported(tmp_path):
    (tmp_path / "plain.txt").write_text(_RESUME_WEAK, encoding="utf-8")
    result = match_directory(_JD, tmp_path)
    assert result.matched == 1


def test_batch_empty_dir_returns_zero_total(tmp_path):
    result = match_directory(_JD, tmp_path)
    assert (result.total, result.matched, result.failed, result.entries) == (0, 0, 0, [])


def test_batch_missing_dir_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        match_directory(_JD, tmp_path / "no_such_dir")


def test_batch_oversize_file_fails_without_scoring(resume_dir, monkeypatch):
    (resume_dir / "big.md").write_text("x" * 100, encoding="utf-8")
    monkeypatch.setattr(batch_mod, "MAX_TEXT_CHARS", 10)
    result = match_directory(_JD, resume_dir)
    big = next(e for e in result.entries if e.resume_path == "big.md")
    assert big.result is None
    assert "上限" in big.error


def test_batch_kwargs_passthrough_no_semantic(resume_dir):
    result = match_directory(_JD, resume_dir, use_semantic=False)
    assert all(e.result.provider == "disabled" for e in result.entries)


def test_batch_result_json_serializable(resume_dir):
    result = match_directory(_JD, resume_dir)
    data = result.model_dump()
    assert data["matched"] == 2
    assert data["entries"][0]["result"]["total_score"] >= data["entries"][1]["result"]["total_score"]


def test_batch_passed_gate_filter(resume_dir):
    result = match_directory(_JD, resume_dir)
    top_score = result.entries[0].result.total_score
    assert len(result.passed(top_score)) == 1
    assert result.passed(101.0) == []
