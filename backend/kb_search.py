#!/usr/bin/env python3
"""志愿Agent — 知识仓库关键词搜索

按业务语义分类检索：高考志愿相关查询优先搜索核心目录，
避免将 _模板、scratch、12_skills 等非业务目录混入结果。
"""
from .config import KB_DIR, KB_DATABASE_FILE

_kb_files = []  # [{path, file, category}]

# 优先检索的核心目录（高考志愿问答）
PRIMARY_DIRS = {
    "01_政策规则", "02_省份数据", "03_院校库", "04_专业库",
    "05_张雪峰风格库", "06_案例库", "07_录取数据", "08_提示词模板",
}

# 根目录下的独立文档
ROOT_DOCS = {
    "00_全国高考地图.md",
    "全国高考地图.md",
    "00_文档关系图谱.md",
}


def scan_kb():
    """扫描知识仓库中所有 .md 文件，并标记所属分类"""
    global _kb_files
    _kb_files = []
    if not KB_DIR.exists():
        return
    for md in KB_DIR.rglob("*.md"):
        rel = md.relative_to(KB_DIR)
        path_str = str(rel).replace("\\", "/")

        # 确定分类
        parts = path_str.split("/")
        if len(parts) == 1:
            # 根目录文件
            category = "root" if parts[0] in ROOT_DOCS else "other"
        else:
            top_dir = parts[0]
            category = "primary" if top_dir in PRIMARY_DIRS else "secondary"

        _kb_files.append({"path": path_str, "file": md, "category": category})
    print(f"[kb] 知识仓库 {len(_kb_files)} 个文件")
    return _kb_files


def kb_search(query, max_files=15):
    """根据关键词搜索知识仓库，返回最相关文件片段

    搜索策略：
    1. 所有文件先做路径关键词匹配（primary/根目录文件有加分）
    2. 路径匹配命中后读取文件头部做内容匹配
    3. 按优先级分组返回：先 primary，再 secondary，填满 max_files
    """
    if not query:
        return []
    words = query.replace(",", " ").replace("、", " ").split()
    words = [w for w in words if len(w) >= 2]
    if not words:
        return []

    scored = []
    for entry in _kb_files:
        score = 0
        path = entry["path"]

        # 路径关键词匹配
        for w in words:
            if w in path:
                score += 5
                if entry["category"] == "primary":
                    score += 3  # 核心目录额外加分
                elif entry["category"] == "root":
                    score += 2

        if score == 0:
            continue

        # 内容匹配（只读文件头部）
        try:
            with open(entry["file"], "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(800)
            for w in words:
                if w in head:
                    score += 2
            if score > 0:
                scored.append((score, entry["category"], entry["path"], head))
        except Exception:
            pass

    # 排序：优先级 (primary=0, root=1, secondary=2) → 分数降序
    category_order = {"primary": 0, "root": 1, "secondary": 2, "other": 3}
    scored.sort(key=lambda x: (category_order.get(x[1], 3), -x[0]))

    results = []
    for score, category, path, content in scored[:max_files]:
        results.append(f"[知识仓库: {path}]\n{content[:600]}")
    return results


def kb_file_count():
    return len(_kb_files)


# 启动时扫描
scan_kb()