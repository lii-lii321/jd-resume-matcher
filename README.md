# jd-resume-matcher

JD↔简历结构化匹配与解释器：纯离线规则抽取 + 多因素加权打分，**每条推荐理由都能回溯到 JD/简历原文的证据片段**。

> 设计动机：招聘筛选不该是黑盒打分。本项目把"为什么推荐/为什么不推荐"拆成逐因素、带证据的解释链路，与可解释推荐（如 smart_tutor 的学习路径推荐）同一思路：先结构化、再建模、最后解释。

## 功能特性

- **输入**：职位描述 + 简历文本（Markdown / 纯文本均可）
- **解析**：规则 + 关键词抽取技能（40+ 规范名，含别名归一）、学历阶梯、工作年限、领域标签，**不依赖 LLM，离线可跑、结果确定**
- **打分**：六因素加权 `total_score` + `score_breakdown` + 逐条 `reasons`，权重集中在 `matcher/constants.py` 并逐条注明设计依据
- **语义路**：嵌入 provider 可插拔 —— `mock`（确定性字符 3-gram 哈希，默认）与 `openai_compatible`（可选）；无 API Key / URL 非法 / 调用失败时**三级优雅降级**到纯规则
- **交付**：FastAPI `/match` 端点 + CLI 演示命令 + 62 个 pytest 全绿

## 架构

```mermaid
flowchart LR
    A[JD 文本] --> P[规则解析器<br/>taxonomy + 正则]
    B[简历文本] --> P
    P --> J[ParsedProfile JD]
    P --> R[ParsedProfile 简历]
    J --> S[加权打分器<br/>constants 权重]
    R --> S
    E[嵌入 Provider<br/>mock / openai_compatible] -.语义因素 0.05.-> S
    E -.缺 Key/失败自动降级.-> S
    S --> O[MatchResult<br/>total_score + breakdown<br/>reasons × 证据片段]
    O --> API[FastAPI /match]
    O --> CLI[cli.py 演示报告]
```

## 快速开始

```bash
# 1. 安装（Python 3.10+）
pip install -r requirements.txt

# 2. CLI 演示：内置示例，零参数可跑
python cli.py --demo

# 3. CLI：指定 JD 与简历文件
python cli.py examples/jd_backend.md examples/resume_strong.md

# 4. 启动 API
uvicorn matcher.main:app --port 8000
```

调用 `/match`：

```bash
curl -X POST http://127.0.0.1:8000/match -H "Content-Type: application/json" -d @- <<'EOF'
{
  "jd_text": "任职要求：本科及以上学历，3年 Python 经验，熟练 FastAPI、MySQL。",
  "resume_text": "计算机专业硕士，5年 Python 经验，熟练 FastAPI 与 MySQL。"
}
EOF
```

响应核心字段：`total_score`（0-100）、`grade`/`grade_label`（A 强烈推荐 / B 推荐 / C 待定 / D 不匹配）、`score_breakdown`（逐因素：基础权重、生效权重、得分、理由）、每条 `reason` 附 `evidence[]`（原文片段 + 字符偏移 + 来自 JD/简历）。

可选命令行参数：`--no-semantic`（纯规则）、`--json`、`--min-score N`（低于阈值退出码 1，可做流水线闸门）、`--provider openai_compatible --base-url ... --model ...`。

## 评分设计

权重集中在 `matcher/constants.py`（单一事实来源），设计依据写在常量注释里：

| 因素 | 基础权重 | 设计依据 |
|---|---|---|
| required_skills | 0.40 | 技能是"能不能干活"最直接信号 |
| preferred_skills | 0.10 | 加分项只做平滑，不当硬门槛 |
| experience | 0.20 | 与产出相关但简历自述易注水，低于技能 |
| education | 0.15 | 常见硬门槛但对实际产出区分度有限 |
| domain | 0.10 | 同领域经验降上手成本，属加分 |
| semantic | 0.05 | 规则漏召回的兜底信号，噪声大只给小权重 |

两个关键机制：

- **权重重分配**：JD 没写学历/领域/加分项时，对应因素禁用，其权重按比例摊回其余因素 —— 不同 JD 的总分始终 0-100 且可比；
- **证据回溯**：所有命中先在原文定位（`start`/`end` 字符偏移），理由引用证据而非凭空生成，测试强制校验 `source_text[start:end] == evidence.text`。

语义因素的可选 provider：

```bash
# mock（默认，确定性、离线）
python cli.py --demo

# openai 兼容端点（API Key 只从环境变量读取，仓库零密钥）
set EMBEDDING_API_KEY=<你的key>          # 占位符，切勿提交真实密钥
python cli.py --demo --provider openai_compatible --base-url https://api.openai.com/v1
```

provider 不可用时自动降级并在 `degraded_note` 里说明原因，打分永不因语义路失败而中断。

## 真实指标

本机（Windows 10，Python 3.10.9）实测，以下数字均为真实运行结果：

- **测试**：`python -m pytest -q` → `62 passed in 1.54s`
- **依赖**：`requirements.txt` 钉死本机实测通过的精确版本（CI 可复现）；`pyproject.toml` 提供库语义的版本范围
- **示例匹配**（`examples/` 四组真实运行）：

| JD | 简历 | 总分 | 等级 |
|---|---|---|---|
| jd_backend.md | resume_strong.md | 88.0 | A 强烈推荐 |
| jd_backend.md | resume_gap.md | 42.6 | D 不匹配 |
| jd_data.md | resume_strong.md | 55.0 | C 待定 |
| jd_backend.md | resume_gap.md（--no-semantic） | 43.6 | D 不匹配 |

语义因素关掉的对比说明：gap 简历与后端 JD 字面重叠低，mock 语义分低于其余因素均值，开启后总分略降 1 分 —— 小权重信号双向起作用，属预期行为而非缺陷。

## 项目结构

```
jd-resume-matcher/
├── matcher/
│   ├── constants.py    # 权重与阈值（含设计依据）
│   ├── taxonomy.py     # 技能/学历/领域词表
│   ├── models.py       # Pydantic 模型（Evidence 是可解释性最小单元）
│   ├── parser.py       # 规则解析器
│   ├── scoring.py      # 加权打分器
│   ├── embeddings.py   # 可插拔 provider + URL 安全校验
│   ├── service.py      # 服务层管线（API 与 CLI 共用）
│   └── main.py         # FastAPI 入口
├── cli.py              # CLI 演示命令
├── examples/           # 示例 JD 与简历
├── tests/              # 62 个测试
├── pyproject.toml      # 包元数据与依赖范围（精确锁定见 requirements.txt）
└── .github/workflows/ci.yml
```

## 已知限制

诚实清单，按影响排序：

1. **词表覆盖有限**：未收录的技能/别名（尤其新兴框架）识别不出；无分词器，复杂中文句式可能漏抽。
2. **必须/加分区分依赖分节标记**：JD 需含"加分项/优先"等标记才会拆分加分技能；无标记的 JD 全部技能按必须项计分，可能低估候选人。
3. **mock 语义无真正泛化**：字符 3-gram 哈希只反映字面重叠，同义改写识别不了；`SEMANTIC_COSINE_CEILING=0.85` 是经验校准值。
4. **出网安全限制是双向的**：SSRF 防护拒绝内网/保留地址，因此 provider 无法指向本机 ollama 等私有端点；DNS 解析后复核存在 TOCTOU 窗口，重绑定攻击不在防护范围。
5. **年限抽取较保守**：只认 0.5-50 区间的数字/中文数字；"两年半""应届生"等表述不识别，超范围数字（如"2020年"）按年份误报过滤。
6. **学历归一有假设**："研究生"默认按硕士；`b.s.` 等带点缩写因整词边界实现可能漏识别。
7. **专业仅解析不打分**：简历专业名与 JD"计算机相关"没有对齐词表，专业匹配只出现在解析结果里。
8. **无鉴权**：`/match` 适合本地/内网演示；公网部署需自行加网关鉴权与限流（输入已限 5 万字符）。

## License

MIT
