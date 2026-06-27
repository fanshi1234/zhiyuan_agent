#!/usr/bin/env python3
"""志愿Agent — 数据库连接、初始化、迁移"""
import sqlite3
import time
import json
from pathlib import Path

from ..config import DATA_DIR

# 统一使用 conversations.db
DB_FILE = DATA_DIR / "conversations.db"


def get_conn():
    conn = sqlite3.connect(str(DB_FILE))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """创建所有表，并迁移旧数据"""
    conn = get_conn()
    _migrate_data(conn)  # 先迁移旧 schema
    _create_tables(conn)  # 再创建新表和索引
    conn.close()


def _create_tables(conn):
    """创建7张表"""

    # 1. conversations — 保留旧表名兼容
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            pinned INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            deleted_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            message_count INTEGER DEFAULT 0,
            UNIQUE(user_id, session_id)
        )
    """)

    # 2. messages
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'done',
            created_at REAL NOT NULL,
            sequence INTEGER NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)

    # 3. message_chunks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)

    # 4. conversation_summaries
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            summary TEXT NOT NULL,
            message_range_start INTEGER,
            message_range_end INTEGER,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)

    # 5. candidate_profiles
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER UNIQUE NOT NULL,
            province TEXT,
            year INTEGER,
            score INTEGER,
            rank INTEGER,
            subject TEXT,
            family_condition TEXT,
            region_pref TEXT,
            region_avoid TEXT,
            major_pref TEXT,
            school_pref TEXT,
            risk_preference TEXT,
            budget_pref TEXT,
            career_goal TEXT,
            raw_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)

    # 6. message_sources
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_path TEXT,
            source_title TEXT,
            snippet TEXT,
            score REAL,
            created_at REAL NOT NULL,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)

    # 7. users
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL,
            last_login_at REAL,
            is_active INTEGER DEFAULT 1
        )
    """)

    # --- 索引 ---
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_pinned ON conversations(user_id, pinned DESC, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_seq ON messages(conversation_id, sequence)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_message ON message_chunks(message_id, chunk_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_conv ON conversation_summaries(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_message ON message_sources(message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

    conn.commit()


def _migrate_data(conn):
    """迁移旧 schema 和现有数据"""

    # --- 迁移 conversations 表 ---
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='conversations'"
    ).fetchone()

    if schema is not None:
        sql = schema[0]
        # 如果缺少 pinned/archived/deleted_at/message_count 列，加上去
        for col_name, col_def in [
            ('pinned', 'ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0'),
            ('archived', 'ALTER TABLE conversations ADD COLUMN archived INTEGER DEFAULT 0'),
            ('deleted_at', 'ALTER TABLE conversations ADD COLUMN deleted_at REAL'),
            ('message_count', 'ALTER TABLE conversations ADD COLUMN message_count INTEGER DEFAULT 0'),
        ]:
            if col_name not in sql:
                try:
                    conn.execute(col_def)
                except Exception:
                    pass

        # 迁移旧 schema: UNIQUE(session_id) -> UNIQUE(user_id, session_id)
        if "UNIQUE(session_id)" in sql and "UNIQUE(user_id, session_id)" not in sql:
            _migrate_conversations_schema(conn)

    # --- 迁移 messages 表 ---
    msg_schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()

    if msg_schema is not None:
        sql = msg_schema[0]
        for col_name, col_def in [
            ('status', "ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'done'"),
            ('sequence', 'ALTER TABLE messages ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0'),
        ]:
            if col_name not in sql:
                try:
                    conn.execute(col_def)
                except Exception:
                    pass

        # 填充 sequence 字段
        if 'sequence' in sql:
            try:
                conn.execute("""
                    UPDATE messages SET sequence = (
                        SELECT seq FROM (
                            SELECT m2.id, ROW_NUMBER() OVER (PARTITION BY m2.conversation_id ORDER BY m2.id) as seq
                            FROM messages m2
                            WHERE m2.id = messages.id
                        )
                    ) WHERE sequence = 0
                """)
            except Exception:
                # 简化方案：按 conversation_id 分组序号
                convs = conn.execute("SELECT DISTINCT conversation_id FROM messages").fetchall()
                for (cid,) in convs:
                    rows = conn.execute(
                        "SELECT id FROM messages WHERE conversation_id=? AND sequence=0 ORDER BY id", (cid,)
                    ).fetchall()
                    for idx, (mid,) in enumerate(rows):
                        conn.execute("UPDATE messages SET sequence=? WHERE id=?", (idx + 1, mid))

    # --- 从 users.json 导入用户 ---
    _import_users(conn)

    conn.commit()


def _migrate_conversations_schema(conn):
    """从 UNIQUE(session_id) 迁移到 UNIQUE(user_id, session_id)"""
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("""
            CREATE TABLE conversations_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                pinned INTEGER DEFAULT 0,
                archived INTEGER DEFAULT 0,
                deleted_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                message_count INTEGER DEFAULT 0,
                UNIQUE(user_id, session_id)
            )
        """)
        conn.execute("INSERT INTO conversations_new SELECT * FROM conversations")
        conn.execute("DROP TABLE conversations")
        conn.execute("ALTER TABLE conversations_new RENAME TO conversations")
        conn.commit()
    except Exception:
        conn.rollback()


def _import_users(conn):
    """从 users.json 导入到 users 表"""
    users_file = DATA_DIR / "users.json"
    if not users_file.exists():
        return
    try:
        with open(users_file, "r", encoding="utf-8") as f:
            users = json.load(f)
    except Exception:
        return

    now = time.time()
    count = 0
    for u in users:
        username = u.get("username", "").strip()
        pwd_hash = u.get("password_hash", "").strip()
        if not username:
            continue
        existing = conn.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, is_active) VALUES (?, ?, ?, 1)",
            (username, pwd_hash, now)
        )
        count += 1

    if count:
        print(f"[db] 从 users.json 导入了 {count} 个用户到 users 表")


def backup_db(path=None):
    """备份数据库文件"""
    if not DB_FILE.exists():
        return None
    if path is None:
        path = DATA_DIR / f"conversations.db.bak.{int(time.time())}"
    import shutil
    shutil.copy2(str(DB_FILE), str(path))
    return path