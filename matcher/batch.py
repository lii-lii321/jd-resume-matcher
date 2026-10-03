"""批量匹配：一份 JD 对目录下多份简历，产出按总分排序的候选名单。

复用 service 层单条管线（解析 -> provider -> 打分），本模块只负责：
文件枚举（不递归子目录）、读取校验、单份失败不中断整批、结果排序。
"""

from pathlib import Path

from .constants import MAX_TEXT_CHARS
from .models import BatchEntry, BatchResult
from .service import match_jd_resume

# 受支持的简历扩展名（不区分大小写）
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".md", ".txt")


def _list_resume_files(resume_dir: Path) -> list[Path]:
    """目录下的简历文件，按文件名排序保证批次结果可复现。"""
    if not resume_dir.is_dir():
        raise NotADirectoryError(f"简历目录不存在或不是目录：{resume_dir}")
    return sorted(
        (p for p in resume_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: p.name,
    )


def validate_resume_text(content: str) -> str:
    """校验单份简历文本：空文件与超限文件抛 ValueError，不进入打分。"""
    if not content.strip():
        raise ValueError("文件为空")
    if len(content) > MAX_TEXT_CHARS:
        raise ValueError(f"文件超过单份上限 {MAX_TEXT_CHARS} 字符")
    return content


def _read_resume(path: Path) -> str:
    """读取并校验单份简历文本文件。"""
    return validate_resume_text(path.read_text(encoding="utf-8"))


def _sorted_entries(entries: list[BatchEntry]) -> list[BatchEntry]:
    """排序：成功按总分降序在前，失败殿后。"""
    matched = sorted(
        (e for e in entries if e.result is not None),
        key=lambda e: e.result.total_score,
        reverse=True,
    )
    failed = [e for e in entries if e.error is not None]
    return matched + failed


def _summarize(jd_path_label: str, entries: list[BatchEntry]) -> BatchResult:
    """汇总条目为 BatchResult：计数 + 排序。"""
    ordered = _sorted_entries(entries)
    matched = sum(1 for e in ordered if e.result is not None)
    return BatchResult(
        jd_path=jd_path_label,
        total=len(ordered),
        matched=matched,
        failed=len(ordered) - matched,
        entries=ordered,
    )


def match_texts(
    jd_text: str,
    resume_texts: list[tuple[str, str]],
    jd_path_label: str = "<简历列表>",
    **match_kwargs,
) -> BatchResult:
    """对 (文件名, 文本) 列表逐份匹配；单份校验/打分失败只记录 error，不中断整批。

    与 match_directory 共用校验、打分与排序逻辑，供内存中的简历文本
    （如 Streamlit 上传）直接走批量管线，无需落盘。
    其余关键字参数透传给 match_jd_resume，include_profiles 默认改为 False。
    """
    match_kwargs.setdefault("include_profiles", False)
    entries: list[BatchEntry] = []
    for name, content in resume_texts:
        try:
            result = match_jd_resume(
                jd_text=jd_text,
                resume_text=validate_resume_text(content),
                **match_kwargs,
            )
            entries.append(BatchEntry(resume_path=name, result=result))
        except (OSError, ValueError) as exc:  # ValueError: 空文件/超限/解码失败
            entries.append(BatchEntry(resume_path=name, error=str(exc)))
    return _summarize(jd_path_label, entries)


def match_directory(
    jd_text: str,
    resume_dir: str | Path,
    jd_path_label: str = "<JD 文本>",
    **match_kwargs,
) -> BatchResult:
    """对目录下每份简历逐份跑匹配；单份读取/打分失败只记录 error，不中断整批。

    其余关键字参数（use_semantic/provider_name/base_url/model/include_profiles）
    透传给 match_jd_resume，但 include_profiles 默认改为 False（候选名单不需要
    每份简历的结构化画像，避免结果膨胀），可显式传 True 覆盖。
    entries 排序：成功按总分降序在前，失败殿后。
    """
    match_kwargs.setdefault("include_profiles", False)
    files = _list_resume_files(Path(resume_dir))
    entries: list[BatchEntry] = []
    for path in files:
        try:
            resume_text = _read_resume(path)
            result = match_jd_resume(jd_text=jd_text, resume_text=resume_text, **match_kwargs)
            entries.append(BatchEntry(resume_path=path.name, result=result))
        except (OSError, ValueError) as exc:  # OSError: 读权限/磁盘问题; ValueError: 空文件/超限/解码失败
            entries.append(BatchEntry(resume_path=path.name, error=str(exc)))

    return _summarize(jd_path_label, entries)
