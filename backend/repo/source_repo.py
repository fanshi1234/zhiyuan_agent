#!/usr/bin/env python3
"""志愿Agent — message_sources 表 CRUD"""
import time
from .db import get_conn


def save(msg_id, source_type, source_path="", source_title="", snippet="", score=0.0):
    """保存一条来源记录"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO message_sources (message_id, source_type, source_path, source_title, snippet, score, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (msg_id, source_type, source_path, source_title, snippet, score, time.time())
    )
    conn.commit()
    conn.close()


def save_batch(msg_id, sources):
    """批量保存来源记录
    :param sources: list of dict with keys: source_type, source_path, source_title, snippet, score
    """
    conn = get_conn()
    now = time.time()
    for s in sources:
        conn.execute(
            "INSERT INTO message_sources (message_id, source_type, source_path, source_title, snippet, score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, s.get('source_type', ''), s.get('source_path', ''),
             s.get('source_title', ''), s.get('snippet', '')[:500],
             s.get('score', 0.0), now)
        )
    conn.commit()
    conn.close()


def get_by_message(msg_id):
    """获取消息的所有来源"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, source_type, source_path, source_title, snippet, score, created_at "
        "FROM message_sources WHERE message_id=?",
        (msg_id,)
    ).fetchall()
    conn.close()
    return [dict(zip(['id', 'source_type', 'source_path', 'source_title', 'snippet', 'score', 'created_at'], row))
            for row in rows]


def delete_by_message(msg_id):
    """删除消息的来源记录"""
    conn = get_conn()
    conn.execute("DELETE FROM message_sources WHERE message_id=?", (msg_id,))
    conn.commit()
    conn.close()


def count_by_message(msg_id):
    """统计消息来源数量"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM message_sources WHERE message_id=?", (msg_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0