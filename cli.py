"""CLI 演示命令。

用法：
  python cli.py examples/jd_backend.md examples/resume_strong.md
  python cli.py --demo                     # 内置示例对，零参数可跑
  python cli.py jd.txt resume.txt --json   # 机器可读输出
  python cli.py jd.txt resume.txt --min-score 70   # 低于阈值退出码 1，便于流水线闸门
  python cli.py jd.txt --resume-dir resumes/       # 批量模式：一份 JD 对目录下全部简历
                                                   # 按总分降序输出候选名单；
                                                   # 配 --min-score 时无人达标退出码 1
  python cli.py jd.txt --resume-dir resumes/ --csv out.csv   # 批量结果导出 CSV（utf-8-sig）
  python cli.py jd.txt resume.txt --vocab my_vocab.json      # 叠加自定义技能词表（用户条目优先）
"""

import argparse
import json
import sys
from pathlib import Path

from matcher.batch import match_directory
from matcher.export import write_batch_csv
from matcher.service import match_jd_resume
from matcher.taxonomy import load_vocab

_DEMO_JD = """# 招聘：后端开发工程师（Python）

## 岗位职责
- 负责金融数据平台的后端服务设计与开发；
- 参与 API 设计、数据库建模与性能优化。

## 任职要求
- 本科及以上学历，计算机相关专业；
- 3年以上 Python 后端开发经验；
- 熟练使用 FastAPI、MySQL、Redis；
- 熟悉 Docker 容器化部署；
- 有金融或大数据领域经验优先。

## 加分项
- 熟悉 Kafka、Kubernetes；
- 了解机器学习基本概念。
"""

_DEMO_RESUME = """# 陈明的简历

## 基本信息
计算机科学与技术专业，硕士学历。

## 工作经历
XX 金融科技有限公司 | 后端开发工程师 | 4年工作经验
- 使用 Python / FastAPI 开发交易数据服务，QPS 从 800 提升到 5000；
- 设计 MySQL 分库分表方案，使用 Redis 做热点缓存；
- 负责 Docker 化部署与 CI/CD 流水线搭建。

## 技能
Python、FastAPI、MySQL、Redis、Docker、Kafka、机器学习（入门）

## 领域
金融、大数据
"""


def _read_text(path: str) -> str:
    content = Path(path).read_text(encoding="utf-8")
    if not content.strip():
        raise SystemExit(f"错误：文件为空：{path}")
    return content


def _print_report(result, jd_path: str, resume_path: str) -> None:
    print("=" * 64)
    print(f"JD ↔ 简历匹配报告    JD: {jd_path}    简历: {resume_path}")
    print("=" * 64)
    print(f"总分: {result.total_score}    等级: {result.grade}（{result.grade_label}）")
    print(f"语义: {'启用 (' + result.provider + ')' if result.semantic_enabled else '禁用（纯规则）'}")
    if result.degraded_note:
        print(f"降级说明: {result.degraded_note}")
    if result.missing_required_skills:
        print(f"硬性技能缺口: {'、'.join(result.missing_required_skills)}")
    print("-" * 64)
    for f in result.score_breakdown:
        status = "禁用" if f.disabled else f"{f.score:.1f} 分"
        print(f"[{f.factor}] 基础权重 {f.base_weight:.2f} / 生效 {f.effective_weight:.3f} -> {status}")
        for r in f.reasons:
            print(f"  · {r.detail}")
            for ev in r.evidence:
                print(f"      证据[{ev.source}] “{ev.text}” @ {ev.start}:{ev.end}")
    print("=" * 64)


def _print_batch_report(batch) -> None:
    """批量模式摘要：按总分降序的候选名单，细节看单条模式。"""
    print("=" * 64)
    print(f"批量匹配报告    JD: {batch.jd_path}    共 {batch.total} 份（成功 {batch.matched} / 失败 {batch.failed}）")
    print("=" * 64)
    rank = 0
    for entry in batch.entries:
        if entry.result is not None:
            rank += 1
            r = entry.result
            gap = f"    缺口: {'、'.join(r.missing_required_skills)}" if r.missing_required_skills else ""
            print(f"{rank:>3}. {entry.resume_path}    {r.total_score:>5.1f}  {r.grade} {r.grade_label}{gap}")
        else:
            print(f"  ✗ {entry.resume_path}    读取失败：{entry.error}")
    print("=" * 64)


def main(argv: list[str] | None = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="JD↔简历匹配解释器（离线规则 + 可插拔语义）")
    parser.add_argument("jd", nargs="?", help="JD 文本文件路径")
    parser.add_argument("resume", nargs="?", help="简历文本文件路径（批量模式下不传）")
    parser.add_argument("--resume-dir", default=None, help="批量模式：简历目录（.md/.txt，不递归），需同时给 JD 文件")
    parser.add_argument("--csv", default=None, help="批量模式：把候选名单导出为 CSV 文件（utf-8-sig，Excel 友好）")
    parser.add_argument("--demo", action="store_true", help="使用内置示例对运行")
    parser.add_argument("--no-semantic", action="store_true", help="禁用语义因素（纯规则）")
    parser.add_argument("--provider", choices=["mock", "openai_compatible"], default="mock")
    parser.add_argument("--base-url", default=None, help="openai_compatible 的 /v1 根地址")
    parser.add_argument("--model", default=None, help="嵌入模型名")
    parser.add_argument("--vocab", default=None, metavar="路径",
                        help="自定义技能词表 JSON（与内置词表按规范名合并，用户条目优先；格式见 README 自定义词表）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--min-score", type=float, default=None, help="低于该分退出码为 1（批量模式：无人达标退出码 1）")
    args = parser.parse_args(argv)

    skill_taxonomy = None
    if args.vocab:
        try:
            skill_taxonomy = load_vocab(args.vocab)
        except (OSError, ValueError) as exc:
            parser.error(f"自定义词表加载失败：{exc}")

    if args.csv and not args.resume_dir:
        parser.error("--csv 仅支持批量模式（配合 --resume-dir 使用）")

    common_kwargs = dict(
        use_semantic=not args.no_semantic,
        provider_name=args.provider,
        base_url=args.base_url,
        model=args.model,
        include_profiles=False,
        skill_taxonomy=skill_taxonomy,
    )

    if args.demo:
        jd_text, resume_text = _DEMO_JD, _DEMO_RESUME
        jd_label, resume_label = "<内置示例JD>", "<内置示例简历>"
        result = match_jd_resume(jd_text=jd_text, resume_text=resume_text, **common_kwargs)

        if args.json:
            print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        else:
            _print_report(result, jd_label, resume_label)

        if args.min_score is not None and result.total_score < args.min_score:
            print(f"总分 {result.total_score} 低于阈值 {args.min_score}", file=sys.stderr)
            return 1
        return 0

    if args.resume_dir:
        if not args.jd:
            parser.error("批量模式需要提供 JD 文件路径")
        if args.resume:
            parser.error("批量模式只接受 JD + --resume-dir，不支持第二个位置参数")
        resume_dir = Path(args.resume_dir)
        if not resume_dir.is_dir():
            parser.error(f"简历目录不存在：{args.resume_dir}")
        batch = match_directory(
            jd_text=_read_text(args.jd),
            resume_dir=resume_dir,
            jd_path_label=args.jd,
            **common_kwargs,
        )
        if batch.total == 0:
            parser.error(f"目录中没有受支持的简历文件（.md/.txt）：{args.resume_dir}")

        if args.json:
            print(json.dumps(batch.model_dump(), ensure_ascii=False, indent=2))
        else:
            _print_batch_report(batch)

        if args.csv:
            csv_path = write_batch_csv(batch, args.csv)
            print(f"已导出 CSV: {csv_path}（成功 {batch.matched} / 失败 {batch.failed}，utf-8-sig）")

        # 批量闸门语义：无人达标（或全员失败）视为未通过，退出码 1
        if args.min_score is not None and not batch.passed(args.min_score):
            print(f"无人达到阈值 {args.min_score}（最高 {batch.entries[0].result.total_score if batch.matched else '无'}）",
                  file=sys.stderr)
            return 1
        return 0

    if not (args.jd and args.resume):
        parser.error("需要提供 JD 与简历文件路径，或使用 --demo / --resume-dir 批量模式")
    jd_text, resume_text = _read_text(args.jd), _read_text(args.resume)
    jd_label, resume_label = args.jd, args.resume

    result = match_jd_resume(jd_text=jd_text, resume_text=resume_text, **common_kwargs)

    if args.json:
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    else:
        _print_report(result, jd_label, resume_label)

    if args.min_score is not None and result.total_score < args.min_score:
        print(f"总分 {result.total_score} 低于阈值 {args.min_score}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
