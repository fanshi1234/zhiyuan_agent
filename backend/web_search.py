#!/usr/bin/env python3
"""志愿Agent — 联网搜索：Tavily AI Search + 百度网页解析兜底"""
import json
import re
import urllib.request
import urllib.parse

from .models import get_tavily_key


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
    """调用 Tavily AI Search API"""
    output = []
    key = get_tavily_key()
    if not key:
        print("[Tavily] 未配置 API key")
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
        with urllib.request.urlopen(req, timeout=15) as resp:
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
            raw_content = _repair_chinese_encoding(item.get("raw_content", ""))[:300]
            if content:
                output.append(f"{title}: {content}")
            elif raw_content:
                output.append(f"{title}: {raw_content}")
    except Exception as exc:
        print(f"[Tavily] 调用失败: {exc}")
    return output or None


def baidu_fallback(search_text, result_count=5):
    """百度网页搜索解析（Tavily 不可用时的兜底方案）"""
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
        with urllib.request.urlopen(req, timeout=8) as resp:
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
    return output or ["未找到相关内容"]


def web_search(search_text, result_count=5):
    """统一搜索入口：优先 Tavily，失败则用百度"""
    if not search_text:
        return []
    tav_res = tavily_query(search_text, result_count)
    if tav_res:
        return tav_res
    return baidu_fallback(search_text, result_count)