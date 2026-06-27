#!/usr/bin/env python3
"""志愿Agent — 消息管理服务"""
import time
from ..repo.message_repo import (
    save, create_streaming, complete_streaming, set_error,
    save_chunk, get_messages, get_recent_messages, get_message_count,
    get_by_id, get_chunks, clear_chunks, search_in_conversation
)
from ..repo.conversation_repo import increment_message_count, update_timestamp


def save_message(user_id, session_id, conv_id, role, content, status="done"):
    """保存消息并更新计数"""
    msg_id = save(conv_id, role, content, status)
    increment_message_count(user_id, session_id)
    update_timestamp(user_id, session_id)
    return msg_id


def create_streaming_message(user_id, session_id, conv_id):
    """创建 streaming 状态的 assistant 消息"""
    msg_id = create_streaming(conv_id)
    increment_message_count(user_id, session_id)
    update_timestamp(user_id, session_id)
    return msg_id


def complete_message(msg_id, content):
    """完成流式消息"""
    complete_streaming(msg_id, content)


def error_message(msg_id, content=""):
    """标记消息为错误"""
    set_error(msg_id, content)


def append_chunk(user_id, session_id, conv_id, msg_id, chunk, chunk_index):
    """追加流式分片"""
    save_chunk(msg_id, chunk_index, chunk)
    update_timestamp(user_id, session_id)
    return chunk_index


def load_messages(user_id, session_id, conv_id, cursor=None, limit=30):
    """分页加载消息"""
    msgs = get_messages(conv_id, cursor, limit)
    has_more = len(msgs) == limit
    if has_more and msgs:
        # 检查是否还有更多
        first_seq = msgs[0]['sequence']
        count = get_messages(conv_id, first_seq, 1)
        has_more = len(count) > 0
    return {
        "messages": msgs,
        "cursor": msgs[0]['sequence'] if msgs else None,
        "has_more": has_more,
    }


def get_recent_for_context(conv_id, limit=12):
    """获取最近消息用于 LLM 上下文"""
    return get_recent_messages(conv_id, limit)


def count_messages(user_id, session_id, conv_id):
    """统计会话消息数"""
    return get_message_count(conv_id)