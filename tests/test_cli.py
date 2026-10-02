"""CLI 测试：演示模式、JSON 输出与分数闸门；批量模式（--resume-dir）。"""

import json

import pytest

from cli import main

_JD = """任职要求：本科及以上学历，3年以上 Python 后端开发经验，熟练使用 FastAPI、MySQL、Redis；熟悉 Docker。"""

_RESUME = """# 候选人
计算机专业硕士，5年 Python 后端经验。
技能：Python、FastAPI、MySQL、Redis、Docker
"""


def test_demo_runs_successfully(capsys):
    assert main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "总分" in out and "证据" in out


def test_demo_json_output_parses(capsys):
    assert main(["--demo", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert 0.0 <= body["total_score"] <= 100.0
    assert len(body["score_breakdown"]) == 6


def test_demo_min_score_gate_blocks_low_threshold(capsys):
    # 阈值拉满必然不达标 -> 退出码 1
    assert main(["--demo", "--min-score", "99.5"]) == 1


def test_demo_no_semantic_pure_rules(capsys):
    assert main(["--demo", "--no-semantic", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["provider"] == "disabled"


def test_missing_args_exits_with_error():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


# ---------- 批量模式（--resume-dir） ----------

@pytest.fixture()
def batch_dir(tmp_path):
    d = tmp_path / "resumes"
    d.mkdir()
    (d / "one.md").write_text(_RESUME, encoding="utf-8")
    (d / "two_empty.md").write_text("", encoding="utf-8")
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    return jd, d


def test_batch_mode_ranked_report(batch_dir, capsys):
    jd, d = batch_dir
    assert main([str(jd), "--resume-dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "批量匹配报告" in out and "成功 1 / 失败 1" in out
    assert "one.md" in out and "读取失败" in out


def test_batch_mode_json_output(batch_dir, capsys):
    jd, d = batch_dir
    assert main([str(jd), "--resume-dir", str(d), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["total"] == 2 and body["matched"] == 1 and body["failed"] == 1
    assert body["entries"][0]["result"]["total_score"] >= 0.0


def test_batch_mode_min_score_gate_nobody_passes(batch_dir, capsys):
    jd, d = batch_dir
    # 阈值拉满必然无人达标 -> 退出码 1
    assert main([str(jd), "--resume-dir", str(d), "--min-score", "99.5"]) == 1


def test_batch_mode_requires_jd(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--resume-dir", str(tmp_path)])
    assert excinfo.value.code != 0


def test_batch_mode_rejects_second_positional(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([str(jd), "resume.md", "--resume-dir", str(tmp_path)])
    assert excinfo.value.code != 0


def test_batch_mode_rejects_missing_dir(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([str(jd), "--resume-dir", str(tmp_path / "nope")])
    assert excinfo.value.code != 0


def test_batch_mode_rejects_dir_without_supported_files(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    (tmp_path / "resumes").mkdir()
    (tmp_path / "resumes" / "a.docx").write_text(_RESUME, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([str(jd), "--resume-dir", str(tmp_path / "resumes")])
    assert excinfo.value.code != 0
