"""集中管理打分权重与阈值，全部带设计依据。

权重设计依据（主观建模，可按岗位族调整）：
- 技能是"能不能干活"的最直接信号，硬性要求 0.40 + 加分项 0.10，合计占一半；
- 经验年限 0.20：与产出相关性高，但简历自述易注水，权重低于技能；
- 学历 0.15：国内招聘常见硬门槛，但对实际产出区分度有限，居中；
- 领域 0.10：同领域经验降低上手成本，属于加分而非门槛；
- 语义相似度 0.05：作为规则漏召回的兜底信号，噪声大，只给小权重。
"""

from typing import Final

# 因素基础权重，总和 = 1.00
FACTOR_WEIGHTS: Final[dict[str, float]] = {
    "required_skills": 0.40,
    "preferred_skills": 0.10,
    "experience": 0.20,
    "education": 0.15,
    "domain": 0.10,
    "semantic": 0.05,
}

# 某因素因 JD 未提供依据而被禁用时，其权重按比例摊回其余启用因素，
# 保证 total_score 始终落在 0-100 且不同 JD 之间可比。
WEIGHT_REDISTRIBUTE: Final[bool] = True

# 等级门槛：total_score -> (等级, 标签)
GRADE_THRESHOLDS: Final[list[tuple[float, str, str]]] = [
    (85.0, "A", "强烈推荐"),
    (70.0, "B", "推荐"),
    (55.0, "C", "待定"),
    (0.0, "D", "不匹配"),
]

# 经验打分：每缺 1 年扣的分；缺得越多失分越快（线性、有下限 0）
EXPERIENCE_PENALTY_PER_YEAR: Final[float] = 25.0

# 学历打分：低于要求 1 级 / 2 级及以上的分数（不完全清零：学历可被经验部分补偿）
EDUCATION_ONE_LEVEL_BELOW: Final[float] = 55.0
EDUCATION_TWO_OR_MORE_BELOW: Final[float] = 20.0
EDUCATION_UNKNOWN_RESUME: Final[float] = 25.0  # 简历未写学历：无法核实，给低分但不判死

# 语义相似度校准：哈希式 mock 嵌入的余弦普遍偏低，
# 观测同文本对通常 <= 0.85，除以该值映射到 0-100（启发式，见 README 已知限制）
SEMANTIC_COSINE_CEILING: Final[float] = 0.85

# 输入上限：防御性限制，避免解析耗时失控
MAX_TEXT_CHARS: Final[int] = 50_000
