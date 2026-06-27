#!/usr/bin/env python3
"""志愿Agent — 会话管理服务"""
from ..repo.conversation_repo import (
    create, get_by_user_session, update_title, set_pinned, set_archived,
    soft_delete, list_conversations, count_conversations, update_timestamp,
    increment_message_count, exists, get_conv_id, ensure_exists
)
from ..repo.db import get_conn


def create_conversation(user_id, title="", session_id=None):
    """创建新会话"""
    return create(user_id, title, session_id)


def rename_conversation(user_id, session_id, title):
    """重命名会话"""
    conv = get_by_user_session(user_id, session_id)
    if conv is None:
        raise ValueError(f"会话 {session_id} 不存在")
    update_title(user_id, session_id, title)
    return {"ok": True, "title": title}


def pin_conversation(user_id, session_id, pinned=True):
    """置顶/取消置顶"""
    conv = get_by_user_session(user_id, session_id)
    if conv is None:
        raise ValueError(f"会话 {session_id} 不存在")
    set_pinned(user_id, session_id, pinned)
    return {"ok": True, "pinned": pinned}


def archive_conversation(user_id, session_id, archived=True):
    """归档/取消归档"""
    conv = get_by_user_session(user_id, session_id)
    if conv is None:
        raise ValueError(f"会话 {session_id} 不存在")
    set_archived(user_id, session_id, archived)
    return {"ok": True, "archived": archived}


def delete_conversation(user_id, session_id):
    """删除会话（软删除）"""
    conv = get_by_user_session(user_id, session_id)
    if conv is None:
        raise ValueError(f"会话 {session_id} 不存在")
    soft_delete(user_id, session_id)
    return {"ok": True}


def get_conversation(user_id, session_id):
    """获取会话信息"""
    conv = get_by_user_session(user_id, session_id)
    if conv is None:
        raise ValueError(f"会话 {session_id} 不存在")
    return conv


def list_user_conversations(user_id, page=1, limit=50, search="", archived_only=False):
    """分页获取会话列表"""
    convs = list_conversations(user_id, page, limit, search, archived_only)
    total = count_conversations(user_id, search, archived_only)
    return {
        "conversations": convs,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": page * limit < total,
    }


def get_or_create(user_id, session_id, title=""):
    """获取或创建会话，返回 (session_id, conv_id)"""
    if exists(user_id, session_id):
        conv_id = get_conv_id(user_id, session_id)
        return session_id, conv_id
    return create(user_id, title, session_id)


def get_conv_id_or_create(conn, user_id, session_id, title=""):
    """在已有连接中获取或创建，返回 conv_id"""
    return ensure_exists(conn, user_id, session_id, title)