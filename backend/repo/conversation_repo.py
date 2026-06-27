#!/usr/bin/env python3
"""志愿Agent — conversations 表 CRUD"""
import time
import uuid
from .db import get_conn


def create(user_id, title="", session_id=None):
    """创建新会话，返回 (session_id, conversation_id)"""
    if session_id is None:
        session_id = str(uuid.uuid4())[:16]
    conn = get_conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO conversations (user_id, session_id, title, created_at, updated_at, message_count) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (user_id, session_id, title, now, now)
    )
    conv_id = cur.lastrowid
    conn.commit()
    conn.close()
    return session_id, conv_id


def get_by_user_session(user_id, session_id):
    """获取会话行"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, session_id, title, pinned, archived, deleted_at, created_at, updated_at, message_count "
        "FROM conversations WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (user_id, session_id)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(['id', 'session_id', 'title', 'pinned', 'archived', 'deleted_at', 'created_at', 'updated_at', 'message_count'], row))


def get_conv_id(user_id, session_id):
    """获取 conversation.id"""
    conv = get_by_user_session(user_id, session_id)
    return conv['id'] if conv else None


def update_title(user_id, session_id, title):
    """重命名会话"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET title=?, updated_at=? WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (title, time.time(), user_id, session_id)
    )
    conn.commit()
    conn.close()


def set_pinned(user_id, session_id, pinned):
    """置顶/取消置顶"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET pinned=?, updated_at=? WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (1 if pinned else 0, time.time(), user_id, session_id)
    )
    conn.commit()
    conn.close()


def set_archived(user_id, session_id, archived):
    """归档/取消归档"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET archived=?, updated_at=? WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (1 if archived else 0, time.time(), user_id, session_id)
    )
    conn.commit()
    conn.close()


def soft_delete(user_id, session_id):
    """软删除"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET deleted_at=?, updated_at=? WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (time.time(), time.time(), user_id, session_id)
    )
    conn.commit()
    conn.close()


def update_timestamp(user_id, session_id):
    """更新最后活跃时间"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE user_id=? AND session_id=?",
        (time.time(), user_id, session_id)
    )
    conn.commit()
    conn.close()


def increment_message_count(user_id, session_id):
    """消息数+1"""
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET message_count=message_count+1 WHERE user_id=? AND session_id=?",
        (user_id, session_id)
    )
    conn.commit()
    conn.close()


def list_conversations(user_id, page=1, limit=50, search="", archived_only=False):
    """分页获取会话列表，置顶在前，未归档优先"""
    conn = get_conn()
    offset = (page - 1) * limit

    if search:
        rows = conn.execute("""
            SELECT id, session_id, title, pinned, archived, created_at, updated_at, message_count
            FROM conversations
            WHERE user_id=? AND deleted_at IS NULL
              AND (title LIKE ? OR session_id LIKE ?)
            ORDER BY pinned DESC, archived ASC, updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, f"%{search}%", f"%{search}%", limit, offset)).fetchall()
    elif archived_only:
        rows = conn.execute("""
            SELECT id, session_id, title, pinned, archived, created_at, updated_at, message_count
            FROM conversations
            WHERE user_id=? AND deleted_at IS NULL AND archived=1
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, session_id, title, pinned, archived, created_at, updated_at, message_count
            FROM conversations
            WHERE user_id=? AND deleted_at IS NULL AND archived=0
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """, (user_id, limit, offset)).fetchall()

    conn.close()
    return [
        dict(zip(['id', 'session_id', 'title', 'pinned', 'archived', 'created_at', 'updated_at', 'message_count'], row))
        for row in rows
    ]


def count_conversations(user_id, search="", archived_only=False):
    """统计会话总数"""
    conn = get_conn()
    sql = "SELECT COUNT(*) FROM conversations WHERE user_id=? AND deleted_at IS NULL"
    params = [user_id]

    if archived_only:
        sql += " AND archived=1"
    else:
        sql += " AND archived=0"

    if search:
        sql += " AND (title LIKE ? OR session_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row[0] if row else 0


def exists(user_id, session_id):
    """检查会话是否存在"""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM conversations WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (user_id, session_id)
    ).fetchone()
    conn.close()
    return row is not None


def ensure_exists(conn, user_id, session_id, title=""):
    """确保会话存在，不存在则创建，返回 conversation_id"""
    row = conn.execute(
        "SELECT id FROM conversations WHERE user_id=? AND session_id=? AND deleted_at IS NULL",
        (user_id, session_id)
    ).fetchone()
    if row:
        return row[0]
    now = time.time()
    cur = conn.execute(
        "INSERT INTO conversations (user_id, session_id, title, created_at, updated_at, message_count) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (user_id, session_id, title, now, now)
    )
    return cur.lastrowid