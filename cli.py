"""CLI 演示命令。

用法：
  python cli.py examples/jd_backend.md examples/resume_chen.md
  python cli.py --demo                     # 内置示例对，零参数可跑
  python cli.py jd.txt resume.txt --json   # 机器可读输出
  python cli.py jd.txt resume.txt --min-score 70   # 低于阈值退出码 1，便于流水线闸门
"""

import argparse
import json
import sys
from pathlib import Path

from matcher.service import match_jd_resume

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


def main(argv: list[str] | None = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="JD↔简历匹配解释器（离线规则 + 可插拔语义）")
    parser.add_argument("jd", nargs="?", help="JD 文本文件路径")
    parser.add_argument("resume", nargs="?", help="简历文本文件路径")
    parser.add_argument("--demo", action="store_true", help="使用内置示例对运行")
    parser.add_argument("--no-semantic", action="store_true", help="禁用语义因素（纯规则）")
    parser.add_argument("--provider", choices=["mock", "openai_compatible"], default="mock")
    parser.add_argument("--base-url", default=None, help="openai_compatible 的 /v1 根地址")
    parser.add_argument("--model", default=None, help="嵌入模型名")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--min-score", type=float, default=None, help="低于该分退出码为 1")
    args = parser.parse_args(argv)

    if args.demo:
        jd_text, resume_text = _DEMO_JD, _DEMO_RESUME
        jd_label, resume_label = "<内置示例JD>", "<内置示例简历>"
    else:
        if not (args.jd and args.resume):
            parser.error("需要提供 JD 与简历文件路径，或使用 --demo")
        jd_text, resume_text = _read_text(args.jd), _read_text(args.resume)
        jd_label, resume_label = args.jd, args.resume

    result = match_jd_resume(
        jd_text=jd_text,
        resume_text=resume_text,
        use_semantic=not args.no_semantic,
        provider_name=args.provider,
        base_url=args.base_url,
        model=args.model,
        include_profiles=False,
    )

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
