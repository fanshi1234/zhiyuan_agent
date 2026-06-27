#!/usr/bin/env python3
"""志愿Agent — conversation_summaries 表 CRUD"""
import time
from .db import get_conn


def create(conv_id, summary, range_start, range_end):
    """创建会话摘要"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversation_summaries (conversation_id, summary, message_range_start, message_range_end, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (conv_id, summary, range_start, range_end, time.time())
    )
    conn.commit()
    conn.close()


def get_all(conv_id):
    """获取会话的所有摘要，按范围排序"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, summary, message_range_start, message_range_end, created_at "
        "FROM conversation_summaries WHERE conversation_id=? ORDER BY message_range_start ASC",
        (conv_id,)
    ).fetchall()
    conn.close()
    return [dict(zip(['id', 'summary', 'message_range_start', 'message_range_end', 'created_at'], row))
            for row in rows]


def get_latest(conv_id):
    """获取最新摘要"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, summary, message_range_start, message_range_end, created_at "
        "FROM conversation_summaries WHERE conversation_id=? ORDER BY message_range_end DESC LIMIT 1",
        (conv_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(['id', 'summary', 'message_range_start', 'message_range_end', 'created_at'], row))


def get_unsummarized_range(conv_id):
    """获取未摘要的消息范围"""
    latest = get_latest(conv_id)
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE conversation_id=? AND status='done'",
        (conv_id,)
    ).fetchone()
    conn.close()
    max_seq = row[0] if row else 0
    start = (latest['message_range_end'] + 1) if latest else 1
    return start, max_seq


def delete(conv_id):
    """删除会话的所有摘要"""
    conn = get_conn()
    conn.execute("DELETE FROM conversation_summaries WHERE conversation_id=?", (conv_id,))
    conn.commit()
    conn.close()