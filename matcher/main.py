"""FastAPI 入口：POST /match 与 GET /health。"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import __version__
from .constants import MAX_TEXT_CHARS
from .models import MatchResult
from .service import match_jd_resume

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/match", response_model=MatchResult)
def match(req: MatchRequest) -> MatchResult:
    return match_jd_resume(
        jd_text=req.jd_text,
        resume_text=req.resume_text,
        use_semantic=req.use_semantic,
        provider_name=req.embedding_provider,
        base_url=req.embedding_base_url,
        model=req.embedding_model,
        include_profiles=req.include_profiles,
    )
