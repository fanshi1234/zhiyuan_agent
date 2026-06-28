#!/usr/bin/env python3
"""志愿Agent — 联网搜索：Tavily AI Search（带缓存，超时 5s）"""
import json
import re
import time
import urllib.request
import urllib.parse

from .models import get_tavily_key

# 搜索结果缓存: { normalized_query: {"results": [...], "ts": timestamp } }
_search_cache = {}
CACHE_TTL_WEB = 3600       # 普通搜索缓存 1 小时
CACHE_TTL_POLICY = 3600    # 政策/投档线搜索缓存 1 小时
MAX_CACHE_SIZE = 200


def _cache_key(query):
    """缓存 key: 小写 + 去空格"""
    return query.strip().lower()


def _is_policy_query(query):
    """是否为政策/投档线类查询"""
    policy_kw = ['投档线', '招生章程', '政策', '招生计划', '分数线', '最新']
    return any(kw in query for kw in policy_kw)


def _cache_get(query):
    """从缓存获取搜索结果"""
    key = _cache_key(query)
    entry = _search_cache.get(key)
    if not entry:
        return None
    ttl = CACHE_TTL_POLICY if _is_policy_query(query) else CACHE_TTL_WEB
    if time.time() - entry["ts"] > ttl:
        del _search_cache[key]
        return None
    return entry["results"]


def _cache_put(query, results):
    """缓存搜索结果"""
    key = _cache_key(query)
    if len(_search_cache) >= MAX_CACHE_SIZE:
        # 淘汰最旧的
        oldest_key = min(_search_cache, key=lambda k: _search_cache[k]["ts"])
        del _search_cache[oldest_key]
    _search_cache[key] = {"results": results, "ts": time.time()}


def _repair_chinese_encoding(text):
    """修复中文 GBK 编码被错误解析为 Latin-1 的问题"""
    if not text or not isinstance(text, str):
        return text or ""
    try:
        repaired = text.encode("latin-1").decode("gbk", errors="replace")
        if repaired.count("�") < text.count("�"):
            return repaired
    except Exception:
        pass
    return text


def tavily_query(search_text, result_count=5):
    """调用 Tavily AI Search API（超时 5s，失败直接返回 None）"""
    output = []
    key = get_tavily_key()
    if not key:
        return None
    try:
        payload = json.dumps({
            "query": search_text,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": result_count,
            "include_domains": [],
            "exclude_domains": [],
            "topic": "general",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw_bytes = resp.read()
            try:
                data = json.loads(raw_bytes.decode("utf-8"))
            except Exception:
                data = json.loads(raw_bytes.decode("gbk", errors="replace"))
        if data.get("answer"):
            output.append("[AI摘要] " + data["answer"])
        for item in data.get("results") or []:
            if not item:
                continue
            title = _repair_chinese_encoding(item.get("title", ""))
            content = _repair_chinese_encoding(item.get("content", ""))[:400]
            if content:
                output.append(f"{title}: {content}")
    except Exception as exc:
        print(f"[Tavily] 调用失败: {exc}")
    return output or None


def web_search(search_text, result_count=5):
    """统一搜索入口: 缓存 → Tavily（5s 超时），不阻塞兜底"""
    if not search_text:
        return []
    # 命中缓存
    cached = _cache_get(search_text)
    if cached:
        return cached
    # Tavily（5s 超时，失败直接返回空）
    tav_res = tavily_query(search_text, result_count)
    if tav_res:
        _cache_put(search_text, tav_res)
        return tav_res
    return []


def web_search_with_fallback(search_text, result_count=5):
    """带百度兜底的搜索（仅用于用户明确要求联网搜索的场景）"""
    if not search_text:
        return []
    cached = _cache_get(search_text)
    if cached:
        return cached
    tav_res = tavily_query(search_text, result_count)
    if tav_res:
        _cache_put(search_text, tav_res)
        return tav_res
    # Tavily 失败才用百度
    return baidu_fallback(search_text, result_count)


def baidu_fallback(search_text, result_count=5):
    """百度网页搜索解析（仅作为兜底方案）"""
    output = []
    try:
        url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(search_text)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
        patterns = [
            r'<span class="content-right_[^"]*">(.*?)</span>',
            r'class="c-abstract"[^>]*>(.*?)</span>',
            r'<span[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</span>',
        ]
        for pat in patterns:
            matches = re.findall(pat, page)
            for m in matches[:result_count]:
                clean = re.sub(r"<[^>]+>", "", m).strip()
                if len(clean) > 20:
                    output.append(clean[:300])
            if output:
                break
    except Exception as exc:
        print(f"[Baidu] 搜索失败: {exc}")
    return output or []