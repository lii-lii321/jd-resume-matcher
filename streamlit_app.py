"""Streamlit 交互 Demo：单份匹配 + 批量筛选（复用 matcher 核心层，展示层零业务逻辑）。

用法（仓库根目录）：
  streamlit run streamlit_app.py

代码组织：本模块上半部分是与 st.* 无关的纯函数（读输入 -> 调核心 -> 组装展示数据），
可被 pytest 直接测试（见 tests/test_streamlit_app.py）；main() 及 _render_* 只做薄壳渲染。
默认填充 examples/ 的 JD 与简历，页面打开即呈现完整匹配结果（TTFS）。
"""

import json
import sys
from pathlib import Path

# 保证 `streamlit run` 任意工作目录启动时都能 import 同仓库的 matcher 包
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import streamlit as st

from matcher.batch import match_texts
from matcher.constants import MAX_TEXT_CHARS
from matcher.export import batch_to_csv
from matcher.models import BatchResult, MatchResult
from matcher.service import match_jd_resume
from matcher.taxonomy import merged_skill_taxonomy, parse_vocab_document

EXAMPLES_DIR = _REPO_ROOT / "examples"
SUPPORTED_SUFFIXES = (".md", ".txt")

FACTOR_LABELS = {
    "required_skills": "必须技能",
    "preferred_skills": "加分技能",
    "experience": "经验年限",
    "education": "学历",
    "domain": "领域",
    "semantic": "语义相似度",
}


# --------------------------------------------------------------------------
# 纯函数层（不依赖 st.*，pytest 直接覆盖）
# --------------------------------------------------------------------------


def factor_label(factor: str) -> str:
    """因素英文名 -> 中文展示名；未知名原样返回。"""
    return FACTOR_LABELS.get(factor, factor)


def read_text_file(path: Path) -> str:
    """读示例文件；空文件直接报错（与核心层口径一致，不让空输入静默通过）。"""
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"文件为空：{path}")
    return content


def load_example_pair(examples_dir: Path | None = None) -> tuple[str, str]:
    """单份匹配页的默认输入：examples/ 的 JD 与强简历。"""
    base = examples_dir or EXAMPLES_DIR
    return read_text_file(base / "jd_backend.md"), read_text_file(base / "resume_strong.md")


def load_example_batch(examples_dir: Path | None = None) -> tuple[str, list[tuple[str, str]]]:
    """批量筛选页的默认输入：jd_backend.md 对 batch_resumes/ 全部 .md/.txt（按文件名排序）。"""
    base = examples_dir or EXAMPLES_DIR
    jd = read_text_file(base / "jd_backend.md")
    folder = base / "batch_resumes"
    resumes = [
        (p.name, read_text_file(p))
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return jd, resumes


def parse_uploaded_vocab(raw: bytes | None) -> dict[str, list[str]] | None:
    """上传词表 JSON 字节 -> 与内置合并后的技能词表；未上传返回 None，非法内容抛 ValueError。

    与 CLI --vocab 走同一条校验/合并管线（matcher/taxonomy.py）：
    先校验 "skills" 包装结构，再按规范名叠加到内置词表（用户条目优先）。
    """
    if raw is None:
        return None
    doc = json.loads(raw.decode("utf-8"))  # JSONDecodeError 是 ValueError 子类
    user = parse_vocab_document(doc, origin="上传词表")
    return merged_skill_taxonomy(user)


def run_single_match(
    jd_text: str,
    resume_text: str,
    use_semantic: bool = True,
    skill_taxonomy: dict[str, list[str]] | None = None,
) -> MatchResult:
    """调核心层跑单份匹配（不带结构化画像，展示层用不到）。"""
    return match_jd_resume(
        jd_text=jd_text,
        resume_text=resume_text,
        use_semantic=use_semantic,
        include_profiles=False,
        skill_taxonomy=skill_taxonomy,
    )


def run_batch_match(
    jd_text: str,
    resume_items: list[tuple[str, str]],
    use_semantic: bool = True,
    skill_taxonomy: dict[str, list[str]] | None = None,
) -> BatchResult:
    """调核心层跑批量匹配：一份 JD 对 (文件名, 文本) 列表，排序与容错复用 matcher/batch.py。"""
    return match_texts(
        jd_text,
        resume_items,
        jd_path_label="<Streamlit 批量>",
        use_semantic=use_semantic,
        skill_taxonomy=skill_taxonomy,
    )


def weighted_contributions(result: MatchResult) -> dict[str, float]:
    """因素展示名 -> 对总分的贡献分（生效权重 × 因素得分），全部之和即 total_score。

    禁用因素贡献恒为 0，仍出现在图里，方便看出"权重摊回"发生了哪些因素上。
    """
    return {factor_label(f.factor): round(f.effective_weight * f.score, 1) for f in result.score_breakdown}


def reason_rows(result: MatchResult) -> list[dict]:
    """展平全部打分理由：每行含因素名、该因素权重贡献、理由文字、证据片段列表。"""
    rows: list[dict] = []
    for f in result.score_breakdown:
        contribution = round(f.effective_weight * f.score, 1)
        for r in f.reasons:
            rows.append(
                {
                    "factor": factor_label(f.factor),
                    "contribution": contribution,
                    "detail": r.detail,
                    "evidence": [
                        {"text": e.text, "start": e.start, "end": e.end, "source": e.source} for e in r.evidence
                    ],
                }
            )
    return rows


def batch_rows(batch: BatchResult) -> list[dict]:
    """批量结果 -> 排序表行（与 CSV 列同口径：成功在前按分降序，失败殿后）。"""
    rows: list[dict] = []
    rank = 0
    for entry in batch.entries:
        if entry.result is not None:
            rank += 1
            r = entry.result
            rows.append(
                {
                    "名次": rank,
                    "简历": entry.resume_path,
                    "总分": r.total_score,
                    "等级": f"{r.grade} {r.grade_label}",
                    "硬性技能缺口": "、".join(r.missing_required_skills),
                    "语义": r.provider if r.semantic_enabled else "禁用",
                    "错误": "",
                }
            )
        else:
            rows.append(
                {
                    "名次": "",
                    "简历": entry.resume_path,
                    "总分": "",
                    "等级": "",
                    "硬性技能缺口": "",
                    "语义": "",
                    "错误": entry.error or "",
                }
            )
    return rows


def csv_bytes(batch: BatchResult) -> bytes:
    """批量结果 -> utf-8-sig CSV 字节（复用 matcher/export.py，Excel 双击不乱码）。"""
    return batch_to_csv(batch).encode("utf-8-sig")


# --------------------------------------------------------------------------
# Streamlit 薄壳
# --------------------------------------------------------------------------


def _render_single(default_jd: str, default_resume: str) -> None:
    left, right = st.columns(2)
    with left:
        jd_text = st.text_area("职位描述（JD）", value=default_jd, height=340)
    with right:
        resume_text = st.text_area("简历文本", value=default_resume, height=340)
    use_semantic = st.toggle("启用语义因素（mock provider，离线确定性）", value=True)
    vocab_file = st.file_uploader(
        "自定义技能词表（JSON，可选；格式同 CLI --vocab，上传即叠加到内置词表）",
        type=["json"],
        key="single_vocab",
    )
    try:
        skill_taxonomy = parse_uploaded_vocab(vocab_file.getvalue() if vocab_file is not None else None)
    except ValueError as exc:
        st.error(f"自定义词表加载失败：{exc}")
        return

    jd_text, resume_text = jd_text.strip(), resume_text.strip()
    if not jd_text or not resume_text:
        st.info("请在两侧分别粘贴 JD 与简历文本。")
        return
    if max(len(jd_text), len(resume_text)) > MAX_TEXT_CHARS:
        st.error(f"单侧输入超过上限 {MAX_TEXT_CHARS} 字符（与核心层口径一致）。")
        return

    result = run_single_match(jd_text, resume_text, use_semantic=use_semantic, skill_taxonomy=skill_taxonomy)

    m1, m2, m3 = st.columns(3)
    m1.metric("总分", f"{result.total_score}")
    m2.metric("等级", f"{result.grade} · {result.grade_label}")
    m3.metric("语义路", result.provider if result.semantic_enabled else "禁用（纯规则）")
    if result.degraded_note:
        st.warning(f"降级说明：{result.degraded_note}")
    if result.missing_required_skills:
        st.error("硬性技能缺口：" + "、".join(result.missing_required_skills))

    st.subheader("逐因素贡献")
    st.bar_chart(
        pd.DataFrame({"贡献分": weighted_contributions(result)}),
        horizontal=True,
        x_label="贡献分（生效权重 × 因素得分）",
    )
    st.caption(
        "贡献 = 生效权重 × 因素得分，全部因素之和即总分；"
        "JD 未提供依据的因素被禁用（贡献 0，其权重按比例摊回其余因素）。"
    )

    st.subheader("打分理由（含权重贡献与证据片段）")
    for row in reason_rows(result):
        st.markdown(f"- **[{row['factor']} · 贡献 {row['contribution']:.1f} 分]** {row['detail']}")
        for ev in row["evidence"]:
            source = "JD" if ev["source"] == "jd" else "简历"
            st.markdown(f"  - 证据[{source}] “{ev['text']}” @ {ev['start']}:{ev['end']}")


def _render_batch(default_jd: str, example_items: list[tuple[str, str]]) -> None:
    jd_text = st.text_area("职位描述（JD）", value=default_jd, height=220, key="batch_jd")
    uploaded = st.file_uploader(
        "上传简历文件（.md/.txt，可多选）；不上传时使用 examples/batch_resumes/ 的三份示例",
        type=["md", "txt"],
        accept_multiple_files=True,
    )
    use_semantic = st.toggle("启用语义因素（mock provider）", value=True, key="batch_semantic")
    vocab_file = st.file_uploader(
        "自定义技能词表（JSON，可选；格式同 CLI --vocab，对批量同样生效）",
        type=["json"],
        key="batch_vocab",
    )
    try:
        skill_taxonomy = parse_uploaded_vocab(vocab_file.getvalue() if vocab_file is not None else None)
    except ValueError as exc:
        st.error(f"自定义词表加载失败：{exc}")
        return

    if uploaded:
        # errors="replace"：Demo 场景下非 UTF-8 字节以占位符呈现而非整份失败
        items = [(f.name, f.getvalue().decode("utf-8", errors="replace")) for f in uploaded]
        source_label = f"上传的 {len(items)} 份文件"
    else:
        items = example_items
        source_label = f"示例目录 examples/batch_resumes/ 的 {len(items)} 份文件"
    st.caption(f"当前对比对象：{source_label}。")

    jd_text = jd_text.strip()
    if not jd_text:
        st.info("请先粘贴 JD 文本。")
        return
    batch = run_batch_match(jd_text, items, use_semantic=use_semantic, skill_taxonomy=skill_taxonomy)

    if batch.total == 0:
        st.info("没有可比较的简历文件。")
        return

    st.subheader(f"候选名单（成功 {batch.matched} / 失败 {batch.failed}，按总分降序）")
    st.dataframe(batch_rows(batch), width="stretch", hide_index=True)
    st.download_button(
        "下载 CSV（utf-8-sig，Excel 友好）",
        data=csv_bytes(batch),
        file_name="ranked_resumes.csv",
        mime="text/csv",
    )
    st.caption(
        "CSV 列与 CLI --csv 导出完全一致（matcher/export.py）：rank, resume_path, total_score, grade, "
        "grade_label, missing_required_skills, semantic_enabled, provider, error。"
    )


def main() -> None:
    st.set_page_config(page_title="JD↔简历匹配器", layout="wide")
    st.title("JD ↔ 简历匹配解释器")
    st.caption(
        "离线规则抽取 + 六因素加权打分，每条理由都可回溯到 JD/简历原文的证据片段。"
        "示例数据已预填，改动文本即实时重算；语义因素默认使用 mock provider，无需任何 API Key。"
    )

    default_jd, default_resume = load_example_pair()
    batch_default_jd, example_items = load_example_batch()

    tab_single, tab_batch = st.tabs(["单份匹配", "批量筛选"])
    with tab_single:
        _render_single(default_jd, default_resume)
    with tab_batch:
        _render_batch(batch_default_jd, example_items)


if __name__ == "__main__":
    main()
