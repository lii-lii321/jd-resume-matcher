"""Pydantic 数据模型：解析结果、证据片段、打分结果。

证据片段（Evidence）是"可解释性"的最小单元：任何一条打分理由都必须
携带至少一个证据片段，指向 JD 或简历原文中的具体位置（start/end 为
字符偏移，source 标明来自哪一侧），保证 reason -> evidence 可回溯校验。
"""

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """一条证据：原文片段 + 位置 + 来源侧。"""

    text: str = Field(description="命中的原文片段")
    start: int = Field(ge=0, description="片段起始字符偏移")
    end: int = Field(gt=0, description="片段结束字符偏移（不含）")
    source: Literal["jd", "resume"] = Field(description="证据来自 JD 还是简历")


class SkillHit(BaseModel):
    """一个被命中的技能：规范名 + 命中别名 + 全部证据片段。"""

    name: str
    matched_alias: str
    evidence: list[Evidence] = Field(default_factory=list)


class EducationInfo(BaseModel):
    """学历解析结果：rank 数值比较（0 大专 / 1 本科 / 2 硕士 / 3 博士）。"""

    level: str | None = None
    rank: int | None = None
    major: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ExperienceInfo(BaseModel):
    """工作年限解析结果（单位：年）。"""

    years: float | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class DomainInfo(BaseModel):
    """领域标签解析结果。"""

    domains: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ParsedProfile(BaseModel):
    """一侧文本（JD 或简历）的结构化画像。

    skills 为必须项；preferred_skills 仅 JD 侧使用（按"加分项/优先"等
    分节标记拆出），简历侧恒为空。
    """

    skills: list[SkillHit] = Field(default_factory=list)
    preferred_skills: list[SkillHit] = Field(default_factory=list)
    education: EducationInfo = Field(default_factory=EducationInfo)
    experience: ExperienceInfo = Field(default_factory=ExperienceInfo)
    domains: DomainInfo = Field(default_factory=DomainInfo)

    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]

    def preferred_skill_names(self) -> list[str]:
        return [s.name for s in self.preferred_skills]


class Reason(BaseModel):
    """一条可追溯的打分理由：文字说明 + 支撑它的证据片段。"""

    detail: str
    evidence: list[Evidence] = Field(default_factory=list)


class FactorScore(BaseModel):
    """单个因素的得分：原始权重、生效权重、0-100 分、理由列表。"""

    factor: str
    base_weight: float
    effective_weight: float
    score: float = Field(ge=0, le=100)
    reasons: list[Reason] = Field(default_factory=list)
    disabled: bool = False


class MatchResult(BaseModel):
    """最终匹配结果。"""

    total_score: float = Field(ge=0, le=100)
    grade: str
    grade_label: str
    score_breakdown: list[FactorScore]
    missing_required_skills: list[str] = Field(default_factory=list)
    semantic_enabled: bool
    provider: str
    degraded_note: str | None = Field(default=None, description="provider 降级/禁用原因")
    jd_profile: ParsedProfile | None = None
    resume_profile: ParsedProfile | None = None


class BatchEntry(BaseModel):
    """批量匹配中的一份简历：成功则携带 MatchResult，失败则携带 error 说明。"""

    resume_path: str = Field(description="简历文件路径（相对传入目录）")
    result: MatchResult | None = None
    error: str | None = Field(default=None, description="读取/大小校验失败原因；成功时为 None")


class BatchResult(BaseModel):
    """一份 JD 对目录下多份简历的批量匹配汇总。

    entries 已排序：成功条目按 total_score 降序在前，失败条目按文件名序殿后。
    """

    jd_path: str
    total: int
    matched: int
    failed: int
    entries: list[BatchEntry]

    def passed(self, min_score: float) -> list[BatchEntry]:
        """达标简历（total_score >= min_score），供闸门语义复用。"""
        return [e for e in self.entries if e.result is not None and e.result.total_score >= min_score]
