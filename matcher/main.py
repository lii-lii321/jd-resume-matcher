"""FastAPI 入口：POST /match 与 GET /health。"""

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import __version__
from .constants import MAX_TEXT_CHARS
from .models import MatchResult
from .service import match_jd_resume
from .taxonomy import merged_skill_taxonomy

app = FastAPI(
    title="jd-resume-matcher",
    description="JD↔简历结构化匹配与解释器：规则抽取 + 多因素加权打分，理由可追溯到证据片段。",
    version=__version__,
)


class MatchRequest(BaseModel):
    jd_text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS, description="职位描述文本")
    resume_text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS, description="简历文本（Markdown/纯文本）")
    use_semantic: bool = Field(default=True, description="是否启用语义相似度因素")
    embedding_provider: Literal["mock", "openai_compatible"] = Field(default="mock")
    embedding_base_url: str | None = Field(default=None, max_length=2048)
    embedding_model: str | None = Field(default=None, max_length=128)
    include_profiles: bool = Field(default=True, description="响应是否附带双侧结构化画像")
    custom_vocab: dict[str, list[str]] | None = Field(
        default=None,
        description=(
            "自定义技能词表（规范名 -> 非空别名列表），与内置词表按规范名合并、用户条目优先；"
            "上限：500 条目 / 单技能 50 别名 / 单别名 80 字符，结构不符返回 422"
        ),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/match", response_model=MatchResult)
def match(req: MatchRequest) -> MatchResult:
    skill_taxonomy = None
    if req.custom_vocab is not None:
        try:
            skill_taxonomy = merged_skill_taxonomy(req.custom_vocab)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"自定义词表校验失败：{exc}") from exc

    return match_jd_resume(
        jd_text=req.jd_text,
        resume_text=req.resume_text,
        use_semantic=req.use_semantic,
        provider_name=req.embedding_provider,
        base_url=req.embedding_base_url,
        model=req.embedding_model,
        include_profiles=req.include_profiles,
        skill_taxonomy=skill_taxonomy,
    )
