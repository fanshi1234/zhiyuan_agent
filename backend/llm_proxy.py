#!/usr/bin/env python3
"""志愿Agent — LLM 调用：多模型路由、自动故障切换、SSE 流式传输"""
import json
import re
import time
import urllib.request

from .models import (
    _models,
    _max_retries,
    _current_model_idx,
    LLM_ENGINE,
    _health_probe,
)


def call_llm_with_routing(body, on_chunk=None):
    """带多模型路由 + 自动重试的 LLM 调用

    :param body: LLM 请求体（不含 model 字段，由本函数自动填入）
    :param on_chunk: 流式回调，收到每个 token 片段时调用
    :returns: 非流式模式下返回完整文本；流式模式下返回 None
    """
    _health_probe()

    current = None
    if _current_model_idx < len(_models):
        current = _models[_current_model_idx]
    candidates = sorted(
        _models,
        key=lambda m: (0 if m is current else 1, m["latency_ms"] or 99999, m["priority"]),
    )

    last_err = None
    for m in candidates:
        if not m["token"]:
            continue
        real_endpoint = m["endpoint"].rstrip("/")
        req_body = dict(body)
        req_body["model"] = m["name"]
        req = urllib.request.Request(
            real_endpoint,
            data=json.dumps(req_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + m["token"],
            },
        )
        try:
            if on_chunk:
                # ---- 流式模式 (SSE) ----
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for line in resp:
                        text_line = line.decode("utf-8", errors="ignore").strip()
                        if not text_line or not text_line.startswith("data:"):
                            continue
                        payload = text_line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            parsed = json.loads(payload)
                            delta = parsed.get("choices", [{}])[0].get("delta", {})
                            chunk = delta.get("content") or delta.get("reasoning_content") or ""
                            if chunk:
                                on_chunk(chunk)
                        except Exception:
                            pass
                m["last_ok"] = time.time()
                m["failed"] = max(0, m["failed"] - 1)
                _models[_current_model_idx] = m if _current_model_idx < len(_models) else m
                return None
            else:
                # ---- 非流式模式 ----
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                result = None
                for enc in ["utf-8", "gbk", "latin-1"]:
                    try:
                        text = raw.decode(enc)
                        result = json.loads(text)
                        break
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                if result is None:
                    text = raw.decode("utf-8", errors="replace")
                    result = json.loads(text)
                m["last_ok"] = time.time()
                m["failed"] = max(0, m["failed"] - 1)
                msg = result.get("choices", [{}])[0].get("message", {})
                return msg.get("content") or msg.get("reasoning_content") or ""
        except Exception as exc:
            last_err = exc
            m["failed"] += 1
            print(f"[llm] {m['name']} 调用失败 ({m['failed']}x): {exc}")
            if m["failed"] > _max_retries:
                continue
    raise RuntimeError(f"所有模型均调用失败: {last_err}")


def invoke_llm(message_list, model_override=None, temp=0.7, token_limit=None, on_chunk=None):
    """调用 LLM 的统一入口

    :param message_list: [{"role": "user", "content": "..."}, ...]
    :param model_override: 强制指定模型名
    :param temp: 温度参数
    :param token_limit: 最大 token 数
    :param on_chunk: 流式回调
    """
    body = {
        "model": model_override or LLM_ENGINE,
        "messages": message_list,
        "temperature": temp,
    }
    if token_limit:
        body["max_tokens"] = token_limit
    body["stream"] = on_chunk is not None
    return call_llm_with_routing(body, on_chunk=on_chunk)


def extract_user_info(user_message):
    """从用户消息中提取报考关键信息（省份、位次、分数、专业偏好等）"""
    prompt = (
        "从用户的咨询文本中提取关键信息。注意理解中文口语表达：\n"
        "- '一万三''1万3' 表示数字 13000\n"
        "- '我是四川的''川籍' 表示省份 四川\n"
        "- '物化生' 表示物理类，'史政地' 表示历史类\n"
        "- '想学XX专业' → majors 列表\n"
        "- '不学XX''不接受XX' → 不要放进 majors\n"
        "- '不想去XX' → region_avoid 列表\n"
        "- '家庭环境普通''家境一般' 是指经济条件，不是指环境专业！\n"
        "请返回纯 JSON（不要其他文字）：\n"
        '{"province":"","rank":0,"score":0,"subject":"","majors":[],"schools":[],"region_pref":[],"region_avoid":[],"keywords":[]}\n'
        "subject 取值范围: 物理类/历史类/文科/理科/综合/综合改革\n"
        "keywords 为联网搜索关键词建议，例如 '四川 自动化 录取位次 2025'\n"
        f"用户消息: {user_message}"
    )
    raw_reply = invoke_llm([{"role": "user", "content": prompt}], temp=0, token_limit=250)
    if not raw_reply:
        return None
    cleaned = re.sub(r"```[\w]*\n?", "", raw_reply).strip()
    return json.loads(cleaned)