"""嵌入 provider 测试：确定性、降级、URL 安全校验。"""

import pytest

from matcher.embeddings import (
    InvalidEmbeddingUrl,
    MockEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    build_provider,
    cosine,
    validate_public_http_url,
)


def test_mock_deterministic_across_instances():
    a = MockEmbeddingProvider().embed(["金融后端 Python"])
    b = MockEmbeddingProvider().embed(["金融后端 Python"])
    assert a == b


def test_mock_similarity_ordering():
    provider = MockEmbeddingProvider()
    same = provider.score("熟悉 Python 与 FastAPI 的后端", "熟悉 Python 与 FastAPI 的后端")
    diff = provider.score("熟悉 Python 与 FastAPI 的后端", "招聘资深会计，精通税法审计")
    assert same > diff
    assert same > 0.5


def test_mock_vectors_normalized():
    vec = MockEmbeddingProvider()._embed_one("一段普通文本")
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-6


def test_cosine_identical_is_one():
    assert cosine([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)
    assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_build_provider_mock_no_degradation():
    provider, note = build_provider("mock")
    assert isinstance(provider, MockEmbeddingProvider) and note is None


def test_build_provider_openai_degrades_without_key(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    # 127.0.0.1 会被 URL 校验直接拒绝（词法层面，无需 DNS），触发降级
    provider, note = build_provider("openai_compatible", base_url="http://127.0.0.1:9/v1")
    assert isinstance(provider, MockEmbeddingProvider)
    assert note is not None and "降级" in note


def test_build_provider_unknown_falls_back():
    provider, note = build_provider("nonsense")
    assert isinstance(provider, MockEmbeddingProvider) and note is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1/v1",
        "http://192.168.1.5/v1",
        "http://10.0.0.1/v1",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/v1",
        "file:///etc/passwd",
        "http://foo.local/v1",
    ],
)
def test_validate_url_rejects_blocked_targets(url):
    with pytest.raises(InvalidEmbeddingUrl):
        validate_public_http_url(url, resolve=False)


def test_validate_url_allows_public_https():
    validate_public_http_url("https://api.example-llm.com/v1", resolve=False)  # 不抛异常即通过


def test_openai_provider_requires_env_key(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    provider = OpenAICompatibleEmbeddingProvider("https://api.example-llm.com/v1", resolve=False)
    with pytest.raises(Exception, match="EMBEDDING_API_KEY"):
        provider.embed(["hello"])
