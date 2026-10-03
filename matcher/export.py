"""批量结果导出：CSV（utf-8-sig 带 BOM，Excel 直接打开中文不乱码）。

只导出扁平汇总列（名次/路径/总分/等级/缺口/语义状态/错误），不含逐因素
明细——明细请回单条模式或 --json 查看，见 README 已知限制。
"""

import csv
import io
from pathlib import Path

from .models import BatchResult

CSV_HEADER: list[str] = [
    "rank",
    "resume_path",
    "total_score",
    "grade",
    "grade_label",
    "missing_required_skills",
    "semantic_enabled",
    "provider",
    "error",
]


def batch_to_csv(batch: BatchResult) -> str:
    """BatchResult -> CSV 文本。行序与 entries 一致：成功按总分降序，失败殿后。

    失败条目仅填 resume_path 与 error（csv 模块自动处理逗号/引号转义）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    rank = 0
    for entry in batch.entries:
        if entry.result is not None:
            rank += 1
            r = entry.result
            writer.writerow(
                [
                    rank,
                    entry.resume_path,
                    r.total_score,
                    r.grade,
                    r.grade_label,
                    "、".join(r.missing_required_skills),
                    int(r.semantic_enabled),
                    r.provider,
                    "",
                ]
            )
        else:
            writer.writerow(["", entry.resume_path, "", "", "", "", "", "", entry.error])
    return buf.getvalue()


def write_batch_csv(batch: BatchResult, path: str | Path) -> Path:
    """落盘为 utf-8-sig（带 BOM）CSV，返回写入路径。newline='' 交由 csv 控制换行。"""
    out = Path(path)
    out.write_text(batch_to_csv(batch), encoding="utf-8-sig", newline="")
    return out
