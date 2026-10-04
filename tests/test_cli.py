"""CLI 测试：演示模式、JSON 输出与分数闸门；批量模式（--resume-dir）与 CSV 导出。"""

import csv
import io
import json
import re
from pathlib import Path

import pytest

from cli import main

_JD = """任职要求：本科及以上学历，3年以上 Python 后端开发经验，熟练使用 FastAPI、MySQL、Redis；熟悉 Docker。"""

_RESUME = """# 候选人
计算机专业硕士，5年 Python 后端经验。
技能：Python、FastAPI、MySQL、Redis、Docker
"""

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_demo_runs_successfully(capsys):
    assert main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "总分" in out and "证据" in out


def test_demo_json_output_parses(capsys):
    assert main(["--demo", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    result = body["result"]
    assert 0.0 <= result["total_score"] <= 100.0
    assert len(result["breakdown"]) == 6


def test_demo_min_score_gate_blocks_low_threshold(capsys):
    # 阈值拉满必然不达标 -> 退出码 1
    assert main(["--demo", "--min-score", "99.5"]) == 1


def test_demo_no_semantic_pure_rules(capsys):
    assert main(["--demo", "--no-semantic", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["result"]["provider"] == "disabled"


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
    results = body["results"]
    assert len(results) == 2
    assert results[0]["file"] == "one.md"
    assert results[0]["total_score"] >= 0.0 and "error" not in results[0]
    assert results[1]["file"] == "two_empty.md"
    assert "total_score" not in results[1] and results[1]["error"]


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


def test_batch_mode_csv_export(batch_dir, tmp_path, capsys):
    jd, d = batch_dir
    out = tmp_path / "ranked.csv"
    assert main([str(jd), "--resume-dir", str(d), "--csv", str(out)]) == 0
    assert "已导出 CSV" in capsys.readouterr().out
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig，Excel 友好
    rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
    assert rows[0][0] == "rank" and len(rows) == 3  # 表头 + 成功 1 + 失败 1


def test_csv_rejected_outside_batch_mode(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    resume = tmp_path / "resume.md"
    resume.write_text(_RESUME, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([str(jd), str(resume), "--csv", str(tmp_path / "x.csv")])
    assert excinfo.value.code != 0


# ---------- --json 结构化输出（P1-2.4） ----------


def test_single_json_example_files_schema_complete(capsys):
    """examples 真实文件：--json 可解析、字段齐全、贡献之和 ≈ 总分。"""
    assert main([str(_EXAMPLES / "jd_backend.md"), str(_EXAMPLES / "resume_strong.md"), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert set(body) == {"result"}
    result = body["result"]
    for key in (
        "total_score",
        "grade",
        "grade_label",
        "missing_required_skills",
        "semantic_enabled",
        "provider",
        "breakdown",
        "reasons",
    ):
        assert key in result, f"缺少字段 {key}"
    assert 0.0 <= result["total_score"] <= 100.0 and result["grade"] in ("A", "B", "C", "D")
    assert len(result["breakdown"]) == 6
    for factor in result["breakdown"]:
        assert {"factor", "base_weight", "effective_weight", "score", "contribution", "disabled"} <= set(factor)
        assert factor["disabled"] == (factor["effective_weight"] == 0.0)
    total = sum(f["contribution"] for f in result["breakdown"])
    assert abs(total - result["total_score"]) < 0.5  # 逐项四舍五入误差以内


def test_single_json_reasons_evidence_traceable(capsys):
    """理由逐条带因素标签；证据片段含来源与偏移，且偏移在原文件中可回溯。"""
    jd_path, resume_path = _EXAMPLES / "jd_backend.md", _EXAMPLES / "resume_strong.md"
    assert main([str(jd_path), str(resume_path), "--json"]) == 0
    reasons = json.loads(capsys.readouterr().out)["result"]["reasons"]
    assert reasons
    texts = {jd_path.read_text(encoding="utf-8"), resume_path.read_text(encoding="utf-8")}
    for reason in reasons:
        assert reason["text"] and reason["factor"]
        for ev in reason["evidence"]:
            assert ev["source"] in ("jd", "resume")
            assert ev["snippet"]
            assert isinstance(ev["start"], int) and isinstance(ev["end"], int)
            assert 0 <= ev["start"] < ev["end"]
            assert any(ev["snippet"] in t for t in texts)  # 片段确为原文子串
            # 字符偏移可回溯：按偏移切原文应精确还原片段
            assert any(t[ev["start"] : ev["end"]] == ev["snippet"] for t in texts)
    assert any(r["evidence"] for r in reasons)  # 命中理由必然携带证据


def test_json_csv_mutually_exclusive_exit_2(tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")
    (tmp_path / "resumes").mkdir()
    (tmp_path / "resumes" / "a.md").write_text(_RESUME, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main([str(jd), "--resume-dir", str(tmp_path / "resumes"), "--json", "--csv", str(tmp_path / "x.csv")])
    assert excinfo.value.code == 2


def test_batch_json_order_matches_text_mode(tmp_path, capsys):
    """批量 --json 的条目顺序与文本模式候选名单一致（总分降序、失败殿后）。"""
    d = tmp_path / "resumes"
    d.mkdir()
    (d / "a_strong.md").write_text(_RESUME, encoding="utf-8")
    (d / "b_weak.md").write_text("了解一点 Python。", encoding="utf-8")
    (d / "c_empty.md").write_text("", encoding="utf-8")
    jd = tmp_path / "jd.txt"
    jd.write_text(_JD, encoding="utf-8")

    assert main([str(jd), "--resume-dir", str(d)]) == 0
    text_order = re.findall(r"\S+\.md", capsys.readouterr().out)

    assert main([str(jd), "--resume-dir", str(d), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""  # 正常路径无多余文本
    body = json.loads(captured.out)
    assert [entry["file"] for entry in body["results"]] == text_order
    scores = [e["total_score"] for e in body["results"] if "total_score" in e]
    assert scores == sorted(scores, reverse=True)
    assert all(e.get("error") for e in body["results"] if "total_score" not in e)


def test_single_json_stdout_pure_json_gate_message_on_stderr(capsys):
    """--json 时 stdout 是纯 JSON；闸门提示只出现在 stderr。"""
    assert main(["--demo", "--json", "--min-score", "99.5"]) == 1
    captured = capsys.readouterr()
    assert captured.out.lstrip().startswith("{")
    assert "result" in json.loads(captured.out)
    assert "低于阈值" in captured.err
