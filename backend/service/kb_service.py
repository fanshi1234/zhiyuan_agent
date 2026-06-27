#!/usr/bin/env python3
"""志愿Agent — 知识库检索服务（整合 kb_search）"""
from ..config import KB_DIR
import re


def search(query, top_k=10):
    """按业务语义分类检索知识库
    返回 [(path, title, content_snippet), ...]
    """
    if not query or not KB_DIR.exists():
        return []

    # 分类目录优先级
    category_map = {
        'policy': ['01_政策规则'],
        'province': ['02_省份数据'],
        'school': ['03_院校库'],
        'major': ['04_专业库'],
        'style': ['05_张雪峰风格库'],
        'case': ['06_案例库'],
        'data': ['07_录取数据'],
        'prompt': ['08_提示词模板'],
    }

    # 判断查询类型
    query_type = _classify_query(query)
    search_dirs = []
    for cat in query_type:
        if cat in category_map:
            search_dirs.extend(category_map[cat])

    # 如果没有匹配的分类，搜索所有核心目录
    if not search_dirs:
        search_dirs = ['01_政策规则', '02_省份数据', '03_院校库', '04_专业库',
                       '05_张雪峰风格库', '06_案例库']

    # 全局导航文件总是搜索
    global_files = []
    for fname in ['00_全国高考地图.md', '00_文档关系图谱.md']:
        fp = KB_DIR / fname
        if fp.exists():
            global_files.append(fp)

    results = []

    # 先搜全局文件
    for fp in global_files:
        score = _score_file(fp, query)
        if score > 0:
            snippet = _get_snippet(fp, query)
            results.append((str(fp.relative_to(KB_DIR)), fp.stem, snippet, score))

    # 按分类目录搜索
    for dir_name in search_dirs:
        dir_path = KB_DIR / dir_name
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            score = _score_file(md_file, query)
            if score > 0:
                snippet = _get_snippet(md_file, query)
                results.append((str(md_file.relative_to(KB_DIR)), md_file.stem, snippet, score))

    # 按分数排序，取 top_k
    results.sort(key=lambda x: x[3], reverse=True)
    return results[:top_k]


def _classify_query(query):
    """根据关键词判断查询类型"""
    types = set()
    q = query.lower()
    if any(k in q for k in ['政策', '规则', '模式', '志愿数', '投档']):
        types.add('policy')
    if any(k in q for k in ['省份', '分数段', '一分一段', '排名', '位次']):
        types.add('province')
    if any(k in q for k in ['大学', '学院', '学校', '985', '211', '双一流']):
        types.add('school')
    if any(k in q for k in ['专业', '就业', '薪资', '前景']):
        types.add('major')
    if any(k in q for k in ['案例', '类似', '参考', '往年']):
        types.add('case')
    return types


def _score_file(filepath, query):
    """简单关键词匹配打分"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(10000)  # 只读前10KB
    except Exception:
        return 0

    keywords = _extract_keywords(query)
    if not keywords:
        return 0

    score = 0
    title = filepath.stem
    for kw in keywords:
        # 标题匹配权重高
        if kw in title:
            score += 10
        # 内容开头匹配
        if kw in content[:500]:
            score += 5
        # 全文匹配
        count = content.lower().count(kw.lower())
        score += count * 0.5

    return score


def _get_snippet(filepath, query, length=300):
    """获取包含关键词的内容片段"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(20000)
    except Exception:
        return ""

    keywords = _extract_keywords(query)
    for kw in keywords:
        idx = content.lower().find(kw.lower())
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(content), idx + length)
            snippet = content[start:end].strip()
            if start > 0:
                snippet = '...' + snippet
            if end < len(content):
                snippet = snippet + '...'
            return snippet

    return content[:length].strip() + '...' if len(content) > length else content.strip()


def _extract_keywords(query):
    """提取搜索关键词"""
    # 移除常见停用词
    stopwords = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一',
                 '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着',
                 '没有', '看', '好', '自己', '这'}
    words = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{2,}', query)
    return [w for w in words if w not in stopwords]


def kb_file_count():
    """统计知识库文件数"""
    if not KB_DIR.exists():
        return 0
    return len(list(KB_DIR.glob("**/*.md")))