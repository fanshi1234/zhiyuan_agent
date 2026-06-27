#!/usr/bin/env python3
"""志愿Agent — 长会话摘要服务"""
import time
from ..repo.summary_repo import create as summary_create, get_latest, get_unsummarized_range, get_all
from ..repo.message_repo import get_messages, get_message_count
from ..llm_proxy import invoke_llm


# 触发阈值
SUMMARY_MSG_THRESHOLD = 20       # 消息数超过此值触发
SUMMARY_TEXT_THRESHOLD = 8000    # 未摘要文本超过此字数触发
SUMMARY_NEW_MSG_THRESHOLD = 10   # 上次摘要后新增消息超过此值触发


def check_and_generate(conv_id):
    """检查是否需要生成摘要，需要则生成"""
    msg_count = get_message_count(conv_id)
    if msg_count < SUMMARY_MSG_THRESHOLD:
        return None

    latest = get_latest(conv_id)
    start, end = get_unsummarized_range(conv_id)
    new_count = end - start + 1

    if new_count < SUMMARY_NEW_MSG_THRESHOLD:
        return None

    # 获取未摘要的消息
    unsummarized = get_messages(conv_id, cursor=start if start > 0 else None, limit=30)
    if not unsummarized:
        return None

    # 计算文本长度
    text_len = sum(len(m.get('content', '')) for m in unsummarized)
    if text_len < SUMMARY_TEXT_THRESHOLD and not latest:
        return None

    # 生成摘要
    summary = _generate_summary(unsummarized)
    if not summary:
        return None

    summary_create(conv_id, summary, start, end)
    return summary


def _generate_summary(messages):
    """调用 LLM 生成摘要"""
    text_parts = []
    for m in messages:
        role_name = '考生' if m['role'] == 'user' else '顾问'
        text_parts.append(f"[{role_name}] {m['content'][:500]}")

    prompt = (
        "你是高考志愿填报助手。请总结以下对话中的关键信息：\n"
        "1. 考生的基本条件（省份、分数、位次、选科）\n"
        "2. 已推荐的学校和专业\n"
        "3. 考生的反馈和偏好变化\n"
        "4. 尚未解决的问题\n"
        "用简洁的段落回答，150字以内。\n\n"
        + '\n'.join(text_parts[:20])
    )

    try:
        reply = invoke_llm([{"role": "user", "content": prompt}], temp=0.3, token_limit=500)
        return reply.strip() if reply else ""
    except Exception as e:
        print(f"[summary] 生成摘要失败: {e}")
        return ""


def get_full_summary(conv_id):
    """获取会话的完整摘要（所有摘要拼接）"""
    summaries = get_all(conv_id)
    if not summaries:
        return ""
    parts = []
    for s in summaries:
        parts.append(f"（第{s['message_range_start']}-{s['message_range_end']}条消息）\n{s['summary']}")
    return '\n\n'.join(parts)