"""jd-resume-matcher：JD↔简历结构化匹配与解释器。

离线规则抽取 + 多因素加权打分，每条推荐理由可追溯到证据片段；
嵌入 provider 可插拔（mock 确定性实现 / openai_compatible，缺 key 自动降级）。
"""

__version__ = "0.1.0"
