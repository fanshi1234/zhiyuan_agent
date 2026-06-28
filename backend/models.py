#!/usr/bin/env python3
"""志愿Agent — AI 模型配置、健康检查、多模型路由"""
import os
import json
import time
import threading
import urllib.request

from .config import AI_CONFIG_FILE

_models = []           # [{name, endpoint, token, priority, latency_ms, last_ok, failed}]
_tavily_key = ""
_health_interval = 60
_health_timeout = 10
_max_retries = 2
_last_health_time = 0
_current_model_idx = 0


def _load_ai_config():
    """从 ai_config.json 加载多模型路由配置"""
    global _models, _tavily_key, _health_interval, _health_timeout, _max_retries
    defaults = {
        "models": [
            {
                "name": "deepseek-v4-flash-ascend",
                "endpoint": "https://api.llm.ustc.edu.cn/v1/chat/completions",
                "token": "",
                "priority": 1,
            },
        ],
        "tavily_search_key": "",
        "health_check_interval": 60,
        "timeout_seconds": 10,
        "max_retries": 2,
    }
    if AI_CONFIG_FILE.exists():
        try:
            cfg = json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                defaults.update(cfg)
        except Exception as e:
            print(f"[ai_config] JSON 解析失败: {e}")

    # 环境变量覆盖（优先级最高）
    models = defaults.get("models", [])
    env_ep = os.getenv("LLM_API_ENDPOINT", "").strip()
    env_tok = os.getenv("LLM_API_TOKEN", "").strip()
    env_mod = os.getenv("LLM_MODEL_NAME", "").strip()
    if env_ep and env_tok:
        models.insert(0, {
            "name": env_mod or "env-model",
            "endpoint": env_ep or "https://api.llm.ustc.edu.cn/v1/chat/completions",
            "token": env_tok or "",
            "priority": 0,
        })

    _models = []
    for i, m in enumerate(sorted(models, key=lambda x: x.get("priority", 99))):
        _models.append({
            "name": m.get("name", f"model-{i}"),
            "endpoint": m.get("endpoint", "").rstrip("/"),
            "token": m.get("token", ""),
            "priority": m.get("priority", i),
            "latency_ms": None,
            "last_ok": 0,
            "failed": 0,
        })
    _tavily_key = os.getenv("TAVILY_SEARCH_KEY", defaults.get("tavily_search_key", ""))
    _health_interval = defaults.get("health_check_interval", 60)
    _health_timeout = defaults.get("timeout_seconds", 10)
    _max_retries = defaults.get("max_retries", 2)

    if not _models:
        _models.append({
            "name": "default",
            "endpoint": "https://api.llm.ustc.edu.cn/v1/chat/completions",
            "token": "", "priority": 0, "latency_ms": None, "last_ok": 0, "failed": 0,
        })


def _best_model():
    """按延迟/故障记录选择最优可用模型"""
    if not _models:
        return None
    candidates = sorted(
        _models,
        key=lambda m: (m["failed"] > _max_retries, m["latency_ms"] or 99999, m["priority"]),
    )
    for m in candidates:
        if m["token"]:
            return m
    return _models[0] if _models else None


def _health_probe():
    """No-op: health check runs in background thread (保留接口兼容)"""
    pass


def _health_probe_once():
    """向各模型发轻量请求以测量延迟"""
    global _current_model_idx
    now = time.time()
    for i, m in enumerate(_models):
        if not m["token"]:
            continue
        try:
            t0 = time.perf_counter()
            payload = json.dumps({
                "model": m["name"],
                "messages": [{"role": "user", "content": "ok"}],
                "max_tokens": 1,
                "temperature": 0,
            }).encode("utf-8")
            req = urllib.request.Request(
                m["endpoint"],
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + m["token"],
                },
            )
            with urllib.request.urlopen(req, timeout=_health_timeout) as resp:
                resp.read()
                elapsed = (time.perf_counter() - t0) * 1000
            m["latency_ms"] = elapsed
            m["last_ok"] = now
            m["failed"] = max(0, m["failed"] - 1)
            if i == 0 or (elapsed < (_models[_current_model_idx]["latency_ms"] or 99999)):
                _current_model_idx = i
            print(f"[health] {m['name']}: {elapsed:.0f}ms")
        except Exception as e:
            m["failed"] += 1
            print(f"[health] {m['name']}: 故障 ({e})")


def _health_loop():
    """后台线程: 每 health_interval 秒执行一次健康检查"""
    global _last_health_time
    while True:
        time.sleep(_health_interval)
        if time.time() - _last_health_time >= _health_interval:
            _last_health_time = time.time()
            _health_probe_once()


def get_tavily_key():
    return _tavily_key


def get_models():
    return list(_models)


def get_current_model_idx():
    return _current_model_idx


# 启动时加载
_load_ai_config()

# 兼容旧变量（供外部引用）
LLM_ENDPOINT = _models[0]["endpoint"] if _models else ""
LLM_TOKEN = _models[0]["token"] if _models else ""
LLM_ENGINE = _models[0]["name"] if _models else ""
TAVILY_TOKEN = _tavily_key

# 启动后台健康检查线程
_health_thread = threading.Thread(target=_health_loop, daemon=True)
_health_thread.start()