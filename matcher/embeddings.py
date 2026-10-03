"""可插拔嵌入 provider。

- MockEmbeddingProvider：确定性字符 3-gram 哈希向量，离线可跑、跨进程稳定
  （用 hashlib 而非内置 hash()，后者跨进程加盐不稳定）；
- OpenAICompatibleEmbeddingProvider：POST {base_url}/embeddings，
  API Key 只从环境变量 EMBEDDING_API_KEY 读取，源码/示例/测试零密钥；
- build_provider：openai_compatible 不可用（缺 key / URL 非法）时自动降级 mock。

安全边界：对外发起 HTTP 前强制校验 URL —— 仅允许 http/https，
拒绝 localhost、环回、私有及保留地址（含 DNS 解析结果复核）。
"""

import hashlib
import ipaddress
import os
import re
import socket
from typing import Literal
from urllib.parse import urlparse

import httpx

MOCK_DIM = 256
NGRAM_SIZE = 3
DEFAULT_TIMEOUT_SECONDS = 10.0
API_KEY_ENV = "EMBEDDING_API_KEY"


class EmbeddingError(Exception):
    """provider 不可用或调用失败。"""


class InvalidEmbeddingUrl(EmbeddingError):
    """URL 未通过安全校验（协议或目标主机不被允许）。"""


_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "instance-data"}
_BLOCKED_NAME_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_http_url(url: str, resolve: bool = True) -> None:
    """校验对外请求 URL：仅 http/https，且主机不是内网/环回/保留地址。

    resolve=True 时对域名做 DNS 解析并逐一复核解析结果（基础防 DNS 绕过；
    TOCTOU 重绑定不在本项目防护范围，见 README 已知限制）。
    测试可传 resolve=False 走纯词法校验。
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidEmbeddingUrl(f"仅允许 http/https 协议，收到：{parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise InvalidEmbeddingUrl("URL 缺少主机名")
    lowered = host.lower()
    if lowered in _BLOCKED_HOSTNAMES or lowered.endswith(_BLOCKED_NAME_SUFFIXES):
        raise InvalidEmbeddingUrl(f"禁止访问内网/元数据主机：{host}")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise InvalidEmbeddingUrl(f"禁止访问私有/环回/保留地址：{host}")
        return
    if not resolve:
        return
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise InvalidEmbeddingUrl(f"主机 DNS 解析失败：{host}（{exc}）") from exc
    for info in infos:
        resolved = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(resolved):
            raise InvalidEmbeddingUrl(f"主机 {host} 解析到受限地址 {resolved}，拒绝请求")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度；任一向量近零时返回 0.0。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


class MockEmbeddingProvider:
    """确定性 mock：字符 3-gram 符号哈希进 256 维向量后 L2 归一化。

    同文本恒得同向量（跨进程稳定），词汇重叠越多余弦越高，
    可作为语义因素的离线默认实现与测试基准。
    """

    name: Literal["mock"] = "mock"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * MOCK_DIM
        normalized = _normalize(text)
        for i in range(max(0, len(normalized) - NGRAM_SIZE + 1)):
            gram = normalized[i: i + NGRAM_SIZE]
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "little") % MOCK_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign
        norm = sum(x * x for x in vec) ** 0.5
        if norm < 1e-12:
            return vec
        return [x / norm for x in vec]

    def score(self, jd_text: str, resume_text: str) -> float:
        va, vb = self.embed([jd_text, resume_text])
        return cosine(va, vb)


class OpenAICompatibleEmbeddingProvider:
    """OpenAI 兼容 /embeddings 端点。API Key 只从环境变量读取。"""

    def __init__(
        self,
        base_url: str,
        model: str = "text-embedding-3-small",
        api_key_env: str = API_KEY_ENV,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        resolve: bool = True,
    ) -> None:
        validate_public_http_url(base_url, resolve=resolve)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.timeout = timeout

    @property
    def name(self) -> str:
        return f"openai_compatible:{self.model}"

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise EmbeddingError(
                f"环境变量 {self.api_key_env} 未设置，无法调用 {self.base_url}"
            )
        return key

    def embed(self, texts: list[str]) -> list[list[float]]:
        key = self._api_key()
        try:
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]
        except EmbeddingError:
            raise
        except Exception as exc:  # 网络/协议/配额等一律归一为不可用
            raise EmbeddingError(f"嵌入请求失败：{exc}") from exc

    def score(self, jd_text: str, resume_text: str) -> float:
        va, vb = self.embed([jd_text, resume_text])
        return cosine(va, vb)


def build_provider(
    provider: str,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[MockEmbeddingProvider | OpenAICompatibleEmbeddingProvider, str | None]:
    """按名称构建 provider；openai_compatible 不可用时降级 mock。

    返回 (provider, 降级原因)；未降级时第二项为 None。
    """
    if provider == "openai_compatible":
        try:
            return OpenAICompatibleEmbeddingProvider(
                base_url or "https://api.openai.com/v1",
                model or "text-embedding-3-small",
            ), None
        except (EmbeddingError, InvalidEmbeddingUrl) as exc:
            return MockEmbeddingProvider(), f"openai_compatible 不可用（{exc}），已降级为 mock"
    if provider != "mock":
        return MockEmbeddingProvider(), f"未知 provider {provider!r}，已回退 mock"
    return MockEmbeddingProvider(), None
