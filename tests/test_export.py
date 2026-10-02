"""CSV 导出测试：列结构与行序、失败条目、BOM 编码与 csv 往返解析。"""

import csv
import io

import pytest

from matcher.batch import match_directory
from matcher.export import CSV_HEADER, batch_to_csv, write_batch_csv
from matcher.models import BatchEntry, BatchResult

_JD = """任职要求：本科及以上学历，3年以上 Python 后端开发经验，熟练使用 FastAPI、MySQL、Redis；熟悉 Docker。加分项：熟悉 Kafka。"""

_RESUME_STRONG = """# 强简历
计算机专业硕士，5年 Python 后端经验。
技能：Python、FastAPI、MySQL、Redis、Docker、Kafka
"""

_RESUME_WEAK = """# 弱简历
计算机专业本科，1年 Python 使用经验。技能：Python
"""


@pytest.fixture()
def batch(tmp_path):
    d = tmp_path / "resumes"
    d.mkdir()
    (d / "a_strong.md").write_text(_RESUME_STRONG, encoding="utf-8")
    (d / "b_weak.md").write_text(_RESUME_WEAK, encoding="utf-8")
    (d / "c_empty.md").write_text("", encoding="utf-8")
    return match_directory(_JD, d)


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_csv_header_and_row_count(batch):
    rows = _rows(batch_to_csv(batch))
    assert rows[0] == CSV_HEADER
    assert len(rows) == batch.total + 1  # 表头 + 每份简历一行


def test_csv_matched_rows_ranked_desc_then_failure_last(batch):
    rows = _rows(batch_to_csv(batch))
    matched, failed = rows[1:3], rows[3]
    assert [r[0] for r in matched] == ["1", "2"]
    scores = [float(r[2]) for r in matched]
    assert scores == sorted(scores, reverse=True)
    assert failed[0] == "" and failed[8]  # 失败行无名次，error 列有内容
    assert failed[1] == "c_empty.md"


def test_csv_matched_row_fields(batch):
    row = _rows(batch_to_csv(batch))[1]
    entry = batch.entries[0]
    assert row[1] == entry.resume_path
    assert float(row[2]) == entry.result.total_score
    assert row[3] == entry.result.grade and row[4] == entry.result.grade_label
    assert row[5] == "、".join(entry.result.missing_required_skills)
    assert row[6] == str(int(entry.result.semantic_enabled))
    assert row[7] == entry.result.provider
    assert row[8] == ""


def test_csv_escapes_comma_and_quotes_in_error():
    # 直接构造失败条目，验证 csv 模块对逗号/引号/换行的转义兜底
    batch = BatchResult(
        jd_path="jd", total=1, matched=0, failed=1,
        entries=[BatchEntry(resume_path='we,ird".md', error='空文件, 含"引号"')],
    )
    rows = _rows(batch_to_csv(batch))
    assert rows[1][1] == 'we,ird".md'
    assert rows[1][8] == '空文件, 含"引号"'


def test_write_batch_csv_uses_utf8_sig_bom(tmp_path, batch):
    out = tmp_path / "out.csv"
    result = write_batch_csv(batch, out)
    assert result == out
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM：Excel 双击打开中文不乱码
    rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8-sig"))))
    assert rows[0] == CSV_HEADER and len(rows) == batch.total + 1
