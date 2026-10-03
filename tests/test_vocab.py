"""词表外置与用户叠加测试：内置 vocab.json 加载、合并语义、--vocab CLI 与打分联动。"""

import json
from pathlib import Path

import pytest

from cli import main
from matcher.service import match_jd_resume
from matcher.taxonomy import SKILL_TAXONOMY, load_vocab

_VOCAB_PATH = Path(__file__).resolve().parent.parent / "matcher" / "data" / "vocab.json"

# 默认词表不认识 Rust：用于验证叠加后新增技能可被识别
_RUST_JD = "任职要求：3年以上 Rust 后端开发经验。"
_RUST_RESUME = "5年 Rust 后端开发经验。"


def _write_user_vocab(tmp_path: Path, skills: dict, with_version: bool = True) -> Path:
    doc = {"skills": skills}
    if with_version:
        doc = {"schema_version": 1, **doc}
    path = tmp_path / "user_vocab.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


# ---------- 内置词表加载 ----------


def test_bundled_vocab_loads_with_valid_structure():
    vocab = load_vocab()
    assert len(vocab) > 0
    for canonical, aliases in vocab.items():
        assert isinstance(canonical, str) and canonical
        assert isinstance(aliases, list) and aliases
        assert all(isinstance(a, str) and a for a in aliases)
    assert vocab == SKILL_TAXONOMY  # 模块级默认与 load_vocab() 同源


def test_vocab_json_carries_schema_and_description():
    doc = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert isinstance(doc["description"], str) and doc["description"]
    assert len(doc["skills"]) == len(load_vocab()) == len(SKILL_TAXONOMY)


# ---------- 叠加合并语义 ----------


def test_load_vocab_merges_add_and_override(tmp_path):
    user = _write_user_vocab(
        tmp_path,
        {
            "Rust": ["rust", "rustlang"],  # 新增
            "Python": ["python"],  # 覆盖（整体替换内置别名列表）
        },
    )
    merged = load_vocab(user)

    assert merged["Rust"] == ["rust", "rustlang"]  # 新增生效
    assert merged["Python"] == ["python"]  # 用户条目优先
    assert merged["Java"] == SKILL_TAXONOMY["Java"]  # 未提及的内置条目保留
    assert set(merged) == set(SKILL_TAXONOMY) | {"Rust"}
    assert load_vocab() == SKILL_TAXONOMY  # 默认加载不受叠加影响


def test_load_vocab_rejects_invalid_user_files(tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_vocab(bad_json)

    missing_skills = tmp_path / "no_skills.json"
    missing_skills.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_vocab(missing_skills)

    bad_aliases = _write_user_vocab(tmp_path, {"Rust": "rust"})
    with pytest.raises(ValueError):
        load_vocab(bad_aliases)

    with pytest.raises(OSError):
        load_vocab(tmp_path / "nope.json")


# ---------- 词表影响打分 ----------


def test_custom_vocab_changes_scoring_result():
    default = match_jd_resume(_RUST_JD, _RUST_RESUME, use_semantic=False, include_profiles=True)
    assert default.jd_profile.skills == []  # 默认词表不认识 Rust

    custom = match_jd_resume(
        _RUST_JD,
        _RUST_RESUME,
        use_semantic=False,
        include_profiles=True,
        skill_taxonomy={**SKILL_TAXONOMY, "Rust": ["rust"]},
    )
    assert [h.name for h in custom.jd_profile.skills] == ["Rust"]
    assert [h.name for h in custom.resume_profile.skills] == ["Rust"]
    assert custom.total_score == 100.0
    assert default.total_score < 50.0  # 技能因素按 JD 无技能要求计 0


def test_default_path_identical_whether_taxonomy_arg_is_none_or_omitted():
    omitted = match_jd_resume(_RUST_JD, _RUST_RESUME, use_semantic=False)
    explicit_none = match_jd_resume(_RUST_JD, _RUST_RESUME, use_semantic=False, skill_taxonomy=None)
    assert omitted.total_score == explicit_none.total_score
    assert omitted.model_dump() == explicit_none.model_dump()


# ---------- CLI --vocab ----------


def test_cli_vocab_flag_enables_new_skill(tmp_path, capsys):
    jd = tmp_path / "jd.txt"
    jd.write_text(_RUST_JD, encoding="utf-8")
    resume = tmp_path / "resume.txt"
    resume.write_text(_RUST_RESUME, encoding="utf-8")

    assert main([str(jd), str(resume), "--json", "--no-semantic"]) == 0
    default_total = json.loads(capsys.readouterr().out)["total_score"]

    vocab = _write_user_vocab(tmp_path, {"Rust": ["rust"]})
    assert main([str(jd), str(resume), "--json", "--no-semantic", "--vocab", str(vocab)]) == 0
    custom_total = json.loads(capsys.readouterr().out)["total_score"]

    assert custom_total == 100.0 and default_total < 50.0


def test_cli_vocab_rejects_missing_file(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["--demo", "--vocab", str(tmp_path / "nope.json")])
    assert excinfo.value.code != 0


def test_cli_vocab_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["--demo", "--vocab", str(bad)])
    assert excinfo.value.code != 0
