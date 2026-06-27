#!/usr/bin/env python3
"""志愿Agent — messages + message_chunks 表 CRUD"""
import time
from .db import get_conn


def save(conv_id, role, content, status="done"):
    """保存一条消息，返回 message_id"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE conversation_id=?",
        (conv_id,)
    ).fetchone()
    seq = row[0] + 1
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, status, created_at, sequence) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, role, content, status, time.time(), seq)
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return msg_id


def create_streaming(conv_id):
    """创建一条 streaming 状态的 assistant 消息，返回 message_id"""
    return save(conv_id, "assistant", "", status="streaming")


def complete_streaming(msg_id, content):
    """完成流式消息：设置内容和状态"""
    conn = get_conn()
    conn.execute(
        "UPDATE messages SET content=?, status='done' WHERE id=?",
        (content, msg_id)
    )
    conn.commit()
    conn.close()


def set_error(msg_id, content=""):
    """标记消息为错误"""
    conn = get_conn()
    conn.execute(
        "UPDATE messages SET content=?, status='error' WHERE id=?",
        (content, msg_id)
    )
    conn.commit()
    conn.close()


def save_chunk(msg_id, chunk_index, content):
    """保存流式分片"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO message_chunks (message_id, chunk_index, content, created_at) "
        "VALUES (?, ?, ?, ?)",
        (msg_id, chunk_index, content, time.time())
    )
    conn.commit()
    conn.close()


def get_messages(conv_id, cursor=None, limit=30):
    """分页加载消息，cursor 为当前最早消息的 sequence，None 表示最近 limit 条"""
    conn = get_conn()
    if cursor is None:
        # 加载最近 limit 条
        rows = conn.execute(
            "SELECT id, role, content, status, created_at, sequence "
            "FROM messages WHERE conversation_id=? AND status!='streaming' "
            "ORDER BY sequence DESC LIMIT ?",
            (conv_id, limit)
        ).fetchall()
        rows = list(reversed(rows))
    else:
        # 加载 cursor 之前的消息
        rows = conn.execute(
            "SELECT id, role, content, status, created_at, sequence "
            "FROM messages WHERE conversation_id=? AND sequence<? AND status!='streaming' "
            "ORDER BY sequence DESC LIMIT ?",
            (conv_id, cursor, limit)
        ).fetchall()
        rows = list(reversed(rows))
    conn.close()
    return [
        dict(zip(['id', 'role', 'content', 'status', 'created_at', 'sequence'], row))
        for row in rows
    ]


def get_recent_messages(conv_id, limit=12):
    """获取最近 N 条消息（用于构建 LLM 上下文）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, role, content, status, created_at, sequence "
        "FROM messages WHERE conversation_id=? AND status!='streaming' "
        "ORDER BY sequence DESC LIMIT ?",
        (conv_id, limit)
    ).fetchall()
    rows = list(reversed(rows))
    conn.close()
    return [
        dict(zip(['id', 'role', 'content', 'status', 'created_at', 'sequence'], row))
        for row in rows
    ]


def get_message_count(conv_id):
    """获取会话消息总数"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id=? AND status!='streaming'",
        (conv_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_unsummarized_text_length(conv_id, last_summary_end):
    """获取未摘要的消息总字数"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUBSTR(group_concat(content, ''), 1, 1), ''), "
        "       COALESCE(SUM(LENGTH(content)), 0) "
        "FROM messages WHERE conversation_id=? AND sequence>? AND status='done'",
        (conv_id, last_summary_end)
    ).fetchone()
    conn.close()
    return row[1] if row else 0


def get_by_id(msg_id):
    """获取单条消息"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, conversation_id, role, content, status, created_at, sequence "
        "FROM messages WHERE id=?",
        (msg_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(['id', 'conversation_id', 'role', 'content', 'status', 'created_at', 'sequence'], row))


def get_chunks(msg_id):
    """获取所有分片"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT chunk_index, content FROM message_chunks WHERE message_id=? ORDER BY chunk_index",
        (msg_id,)
    ).fetchall()
    conn.close()
    return [dict(zip(['chunk_index', 'content'], row)) for row in rows]


def clear_chunks(msg_id):
    """清理分片（合并后）"""
    conn = get_conn()
    conn.execute("DELETE FROM message_chunks WHERE message_id=?", (msg_id,))
    conn.commit()
    conn.close()


def search_in_conversation(conv_id, query, limit=10):
    """在会话中搜索相关消息"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, role, content, created_at, sequence "
        "FROM messages WHERE conversation_id=? AND content LIKE ? AND status='done' "
        "ORDER BY created_at DESC LIMIT ?",
        (conv_id, f"%{query}%", limit)
    ).fetchall()
    conn.close()
    return [dict(zip(['id', 'role', 'content', 'created_at', 'sequence'], row)) for row in rows]