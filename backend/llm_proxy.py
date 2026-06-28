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
)


def call_llm_with_routing(body, on_chunk=None):
    """带多模型路由 + 自动重试的 LLM 调用

    :param body: LLM 请求体（不含 model 字段，由本函数自动填入）
    :param on_chunk: 流式回调，收到每个 token 片段时调用
    :returns: 非流式模式下返回完整文本；流式模式下返回 None
    """
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
                chunk_count = 0
                total_chars = 0
                last_chunk = ""
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
                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning_content") or ""
                            finish = parsed.get("choices", [{}])[0].get("finish_reason")
                            if finish:
                                print(f"[llm] {m['name']} finish_reason={finish}")
                            if reasoning:
                                chunk_count += 1
                                total_chars += len(reasoning)
                                last_chunk = reasoning[:20]
                                on_chunk(reasoning, True)
                            elif content:
                                chunk_count += 1
                                total_chars += len(content)
                                last_chunk = content[:20]
                                on_chunk(content, False)
                        except Exception:
                            pass
                    # drain: upstream 最后一行可能没有换行符
                    remaining_data = resp.read()
                    if remaining_data:
                        drained = 0
                        for line in remaining_data.decode("utf-8", errors="ignore").splitlines():
                            text_line = line.strip()
                            if not text_line or not text_line.startswith("data:"):
                                continue
                            payload = text_line[5:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                parsed = json.loads(payload)
                                delta = parsed.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content") or ""
                                reasoning = delta.get("reasoning_content") or ""
                                if reasoning:
                                    chunk_count += 1
                                    total_chars += len(reasoning)
                                    drained += 1
                                    on_chunk(reasoning, True)
                                elif content:
                                    chunk_count += 1
                                    total_chars += len(content)
                                    drained += 1
                                    on_chunk(content, False)
                            except Exception:
                                pass
                        if drained:
                            print(f"[llm] {m['name']} drain: {drained} chunks from remaining buffer")
                print(f"[llm] {m['name']} stream: {chunk_count} chunks, {total_chars} chars, last=[{last_chunk}...]")
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
    # 设置输出 token 上限，避免上游 API 默认值过小导致回答截断
    if token_limit is not None:
        body["max_tokens"] = token_limit
    else:
        body["max_tokens"] = 16384
    body["stream"] = on_chunk is not None
    if on_chunk:
        total_msg_chars = sum(len(str(m.get("content", ""))) for m in message_list)
        print(f"[llm] invoke model={body['model']} max_tokens={body.get('max_tokens')} msg_chars={total_msg_chars} messages={len(message_list)}")
    return call_llm_with_routing(body, on_chunk=on_chunk)


def extract_user_info(user_message):
    """从用户消息中提取报考关键信息（省份、位次、分数、专业偏好等）"""
    prompt = (
        "你是一个信息提取工具。从用户文本提取关键信息，只返回一行JSON不要其他文字：\n"
        '{"province":"","rank":0,"score":0,"subject":"","majors":[],"schools":[],"region_pref":[],"region_avoid":[],"keywords":[]}\n'
        "物化生→物理类，史政地→历史类。1万3→13000。不想去→region_avoid。家庭环境普通≠环境专业\n"
        f"用户消息: {user_message}"
    )
    raw_reply = invoke_llm([{"role": "user", "content": prompt}], temp=0, token_limit=300)
    if not raw_reply:
        return None
    cleaned = re.sub(r"```[\w]*\n?", "", raw_reply).strip()
    # 从任意位置提取 JSON 对象（支持嵌套括号）
    start = cleaned.find('"province"')
    if start >= 0:
        brace_start = cleaned.rfind('{', 0, start)
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(cleaned)):
                if cleaned[i] == '{':
                    depth += 1
                elif cleaned[i] == '}':
                    depth -= 1
                    if depth == 0:
                        cleaned = cleaned[brace_start:i+1]
                        break
    return json.loads(cleaned)