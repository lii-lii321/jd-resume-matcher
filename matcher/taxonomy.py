"""关键词词表：技能、学历、领域。

设计说明：
- 全部为静态规则词表，离线可用、确定性可测；
- 别名统一映射到规范名（canonical），如 mysql -> SQL、k8s -> Kubernetes；
- 纯 ASCII 别名按整词边界匹配（避免 "sql" 误命中 "mysql" 的反面情况由别名显式覆盖），
  含中文的别名按子串匹配（Python re 的 \\b 对中文无效）。
"""

# 技能词表：规范名 -> 别名列表（第一个别名视为主写法）
SKILL_TAXONOMY: dict[str, list[str]] = {
    "Python": ["python", "python3"],
    "Java": ["java"],
    "Go": ["golang", "go语言", "go 语言"],
    "C++": ["c++"],
    "C#": ["c#", "c sharp"],
    "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript", "ts"],
    "React": ["react", "reactjs"],
    "Vue": ["vue", "vuejs"],
    "Node.js": ["node.js", "nodejs", "node"],
    "FastAPI": ["fastapi"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring": ["spring", "spring boot", "springboot"],
    "SQL": ["sql", "mysql", "postgresql", "postgres", "sqlite", "oracle", "sqlserver"],
    "Redis": ["redis"],
    "MongoDB": ["mongodb", "mongo"],
    "Docker": ["docker", "容器化"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Linux": ["linux"],
    "Git": ["git", "版本管理"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "tf"],
    "机器学习": ["机器学习", "machine learning", "ml"],
    "深度学习": ["深度学习", "deep learning"],
    "NLP": ["自然语言处理", "nlp"],
    "数据分析": ["数据分析", "data analysis"],
    "pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Spark": ["spark", "pyspark"],
    "Hadoop": ["hadoop"],
    "Kafka": ["kafka"],
    "RabbitMQ": ["rabbitmq", "rabbit mq"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Excel": ["excel"],
    "AWS": ["aws", "亚马逊云"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "微服务": ["微服务", "microservice"],
    "RESTful API": ["restful", "rest api", "api 设计"],
    "CI/CD": ["ci/cd", "cicd", "持续集成"],
    "自动化测试": ["自动化测试", "单元测试", "pytest", "unittest"],
    "爬虫": ["爬虫", "spider", "scrapy"],
    "大数据": ["大数据", "big data", "数据仓库", "数仓"],
    "推荐系统": ["推荐系统", "recommendation system"],
    "计算机视觉": ["计算机视觉", "cv", "图像识别"],
}

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
