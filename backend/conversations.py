#!/usr/bin/env python3
"""志愿Agent — 对话数据库操作：存储、查询、删除会话和消息"""
import time
import sqlite3
import uuid
from pathlib import Path

from .config import DATA_DIR

# 对话数据库独立文件（不与录取数据混在一起）
CONVERSATION_DB = DATA_DIR / "conversations.db"


def _get_conn():
    conn = sqlite3.connect(str(CONVERSATION_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_conversations_db():
    """创建对话和消息表，并自动迁移旧 schema"""
    conn = _get_conn()

    # 获取当前表的 schema
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='conversations'"
    ).fetchone()

    if schema is None:
        # 全新建表
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(user_id, session_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_user_session ON conversations(user_id, session_id);
        """)
    elif "UNIQUE(session_id)" in schema[0] or "UNIQUE(user_id, session_id)" not in schema[0]:
        # 迁移旧 schema：从 UNIQUE(session_id) → UNIQUE(user_id, session_id)
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute("""
                CREATE TABLE conversations_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(user_id, session_id)
                )
            """)
            conn.execute("INSERT INTO conversations_new SELECT * FROM conversations")
            conn.execute("DROP TABLE conversations")
            conn.execute("ALTER TABLE conversations_new RENAME TO conversations")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_session ON conversations(user_id, session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
            conn.commit()
        except Exception:
            conn.rollback()
    conn.close()


def _user_session_conv_id(user_id, session_id):
    """获取用户-会话对应的 conversation.id，不存在则返回 None"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM conversations WHERE user_id = ? AND session_id = ?",
        (user_id, session_id)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _generate_session_id():
    """生成全局唯一的会话ID"""
    return str(uuid.uuid4())[:16]


def save_conversation(user_id, session_id, title=""):
    """创建或更新会话（严格按 user_id 隔离）"""
    conn = _get_conn()
    now = time.time()
    # 检查是否已存在其他用户的同 session_id，如有则强制替换为用户自己的
    conn.execute("""
        INSERT INTO conversations (user_id, session_id, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, session_id) DO UPDATE SET
            title = excluded.title,
            updated_at = excluded.updated_at
    """, (user_id, session_id, title, now, now))
    conn.commit()
    conn.close()


def save_message(user_id, session_id, role, content):
    """保存消息（严格按 user_id 隔离）"""
    conv_id = _user_session_conv_id(user_id, session_id)
    if conv_id is None:
        return False
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (conv_id, role, content, time.time())
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (time.time(), conv_id)
    )
    conn.commit()
    conn.close()
    return True


def load_conversations(user_id):
    """加载指定用户的所有会话"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, title, created_at, updated_at FROM conversations "
        "WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,)
    ).fetchall()
    convs = []
    for row in rows:
        convs.append({
            "session_id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
        })
    conn.close()
    return convs


def load_messages(user_id, session_id):
    """加载指定用户-会话的所有消息（严格按 user_id 隔离）"""
    conv_id = _user_session_conv_id(user_id, session_id)
    if conv_id is None:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]


def delete_conversation(user_id, session_id):
    """删除指定用户的会话及其所有消息（严格按 user_id 隔离）"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM conversations WHERE user_id = ? AND session_id = ?",
        (user_id, session_id)
    )
    conn.commit()
    conn.close()


def create_conversation(user_id, title=""):
    """创建新会话，返回 (session_id, conversation_id)"""
    session_id = _generate_session_id()
    conn = _get_conn()
    now = time.time()
    conn.execute(
        "INSERT INTO conversations (user_id, session_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, session_id, title, now, now)
    )
    conv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return session_id, conv_id


def list_user_conversations(user_id, limit=50):
    """列出用户的会话（含消息数量）"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.session_id, c.title, c.updated_at, COUNT(m.id) as msg_count
        FROM conversations c
        LEFT JOIN messages m ON c.id = m.conversation_id
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [
        {"session_id": r[0], "title": r[1], "updated_at": r[2], "msg_count": r[3]}
        for r in rows
    ]


def search_messages(user_id, query, limit=100):
    """搜索用户的消息内容"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.session_id, c.title, m.role, m.content, m.created_at
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE c.user_id = ? AND m.content LIKE ?
        ORDER BY m.created_at DESC
        LIMIT ?
    """, (user_id, f"%{query}%", limit)).fetchall()
    conn.close()
    return [
        {
            "session_id": r[0], "title": r[1],
            "role": r[2], "content": r[3], "created_at": r[4]
        }
        for r in rows
    ]