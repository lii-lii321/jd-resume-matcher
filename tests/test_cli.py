"""CLI 测试：演示模式、JSON 输出与分数闸门。"""

import json

import pytest

from cli import main


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
