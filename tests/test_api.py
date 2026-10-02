"""API 测试：/health 与 /match 的形状、校验与降级行为。"""

from fastapi.testclient import TestClient

from matcher.main import app

client = TestClient(app)

_JD = "任职要求：本科及以上学历，3年 Python 经验，熟练 FastAPI、MySQL。"
_RESUME = "计算机专业硕士，5年 Python 经验，熟练 FastAPI 与 MySQL。"


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_match_returns_full_shape():
    resp = client.post("/match", json={"jd_text": _JD, "resume_text": _RESUME})
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["total_score"] <= 100.0
    assert body["grade"] in {"A", "B", "C", "D"}
    assert len(body["score_breakdown"]) == 6
    assert body["semantic_enabled"] is True and body["provider"] == "mock"
    assert body["jd_profile"]["skills"]


def test_match_reasons_carry_evidence():
    body = client.post("/match", json={"jd_text": _JD, "resume_text": _RESUME}).json()
    evidenced = [
        r for f in body["score_breakdown"] for r in f["reasons"] if r["evidence"]
    ]
    assert evidenced, "至少应有理由携带证据"
    for r in evidenced:
        for ev in r["evidence"]:
            source = _JD if ev["source"] == "jd" else _RESUME
            assert source[ev["start"]:ev["end"]] == ev["text"]


def test_match_validation_error_on_missing_field():
    resp = client.post("/match", json={"jd_text": _JD})
    assert resp.status_code == 422


def test_match_rejects_oversize_input():
    resp = client.post(
        "/match",
        json={"jd_text": "长" * 50_001, "resume_text": _RESUME},
    )
    assert resp.status_code == 422


def test_match_semantic_disabled():
    body = client.post(
        "/match",
        json={"jd_text": _JD, "resume_text": _RESUME, "use_semantic": False},
    ).json()
    assert body["semantic_enabled"] is False and body["provider"] == "disabled"


def test_match_openai_provider_degrades_without_key(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    body = client.post(
        "/match",
        json={
            "jd_text": _JD,
            "resume_text": _RESUME,
            "embedding_provider": "openai_compatible",
            "embedding_base_url": "http://127.0.0.1:9/v1",
        },
    ).json()
    assert body["provider"] == "mock"          # 降级后仍可用
    assert "降级" in (body["degraded_note"] or "")


def test_match_empty_profile_still_scores():
    body = client.post(
        "/match", json={"jd_text": "无具体要求的岗位", "resume_text": "随便写写"}
    ).json()
    assert 0.0 <= body["total_score"] <= 100.0
