"""关键词词表：技能、学历、领域。

设计说明：
- 全部为静态规则词表，离线可用、确定性可测；
- 技能词表外置为包内数据文件 matcher/data/vocab.json（带 schema_version 与
  description 字段），模块导入时经 importlib.resources 加载，装包后同样可用；
- 别名统一映射到规范名（canonical），如 mysql -> SQL、k8s -> Kubernetes；
- 纯 ASCII 别名按整词边界匹配（避免 "sql" 误命中 "mysql" 的反面情况由别名显式覆盖），
  含中文的别名按子串匹配（Python re 的 \\b 对中文无效）。
"""

import json
from importlib.resources import files
from pathlib import Path

# 学历阶梯：rank 越高学历越高；"研究生" 归入硕士（常见口语默认，见 README 已知限制）
EDUCATION_LEVELS: list[dict] = [
    {"rank": 0, "name": "大专", "aliases": ["大专", "专科", "associate degree"]},
    {"rank": 1, "name": "本科", "aliases": ["本科", "学士", "bachelor", "b.s.", "bs", "b.a.", "ba"]},
    {"rank": 2, "name": "硕士", "aliases": ["硕士", "硕士研究生", "研究生", "master", "m.s.", "ms", "m.a.", "ma"]},
    {"rank": 3, "name": "博士", "aliases": ["博士", "博士研究生", "phd", "doctorate", "doctor"]},
]

# 领域词表：规范名 -> 别名
DOMAIN_TAXONOMY: dict[str, list[str]] = {
    "金融": ["金融", "银行", "证券", "保险", "fintech", "基金", "支付"],
    "电商": ["电商", "电子商务", "零售", "e-commerce", "ecommerce"],
    "医疗": ["医疗", "健康", "医药", "healthcare"],
    "教育": ["教育", "在线课程", "education", "培训"],
    "游戏": ["游戏", "gaming"],
    "物流": ["物流", "供应链", "logistics"],
    "社交": ["社交", "社区", "social"],
    "广告": ["广告", "营销", "adtech"],
    "云计算": ["云计算", "云服务", "cloud"],
    "人工智能": ["人工智能", "ai", "artificial intelligence"],
    "大数据": ["大数据", "数据服务", "big data"],
    "网络安全": ["网络安全", "信息安全", "security"],
    "汽车": ["汽车", "自动驾驶", "automotive"],
    "政务": ["政务", "government", "公共部门"],
    "教育科技": ["edtech"],
}


def _parse_vocab_document(raw: str, origin: str) -> dict[str, list[str]]:
    """解析词表 JSON 文本并校验结构，返回 规范名 -> 别名列表。

    要求顶层对象含 "skills" 字段（规范名 -> 非空别名列表）；schema_version /
    description 为注释性字段，加载时不校验其取值。结构非法抛 ValueError。
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{origin} 不是合法 JSON：{exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{origin} 顶层必须是 JSON 对象")
    skills = doc.get("skills")
    if not isinstance(skills, dict):
        raise ValueError(f"{origin} 缺少 \"skills\" 字段（应为 规范名 -> 别名列表 的对象）")

    taxonomy: dict[str, list[str]] = {}
    for canonical, aliases in skills.items():
        if not isinstance(canonical, str) or not canonical.strip():
            raise ValueError(f"{origin} 存在空的技能规范名")
        if not isinstance(aliases, list) or not aliases \
                or not all(isinstance(a, str) and a.strip() for a in aliases):
            raise ValueError(f"{origin} 中技能「{canonical}」的别名必须是非空字符串列表")
        taxonomy[canonical.strip()] = [a.strip() for a in aliases]
    return taxonomy


def _load_bundled_vocab() -> dict[str, list[str]]:
    """读取包内词表 matcher/data/vocab.json（importlib.resources，装包后同样可用）。"""
    raw = files("matcher").joinpath("data").joinpath("vocab.json").read_text(encoding="utf-8")
    return _parse_vocab_document(raw, origin="内置词表 matcher/data/vocab.json")


def load_vocab(extra_path: str | Path | None = None) -> dict[str, list[str]]:
    """加载技能词表：默认内置 vocab.json；传入用户 JSON 时按键合并。

    合并语义：用户文件与内置词表按规范名（canonical）合并，同名条目由用户
    整体覆盖（别名列表不拼接），新规范名直接追加，其余内置条目原样保留。
    文件不存在 / JSON 非法 / 结构不符抛 OSError 或 ValueError。
    """
    taxonomy = _load_bundled_vocab()
    if extra_path is not None:
        path = Path(extra_path)
        raw = path.read_text(encoding="utf-8")
        user = _parse_vocab_document(raw, origin=f"用户词表 {path}")
        taxonomy = {**taxonomy, **user}
    return taxonomy


# 技能词表：规范名 -> 别名列表（第一个别名视为主写法）；内容源为 matcher/data/vocab.json
SKILL_TAXONOMY: dict[str, list[str]] = _load_bundled_vocab()


def flatten_alias_map(taxonomy: dict[str, list[str]]) -> dict[str, str]:
    """把 {规范名: [别名]} 展平为 {小写别名: 规范名}，长别名优先。"""
    alias_map: dict[str, str] = {}
    for canonical, aliases in taxonomy.items():
        for alias in aliases:
            key = alias.lower()
            if key in alias_map and len(alias_map[key]) >= len(canonical):
                continue
            alias_map[key] = canonical
    return alias_map
