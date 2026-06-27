#!/usr/bin/env python3
"""志愿Agent — 用户认证与会话管理"""
import os
import json
import time
import hashlib

from .config import USERS_FILE, SESSION_TTL

_user_db = []      # [{username, password_hash}]
_sessions = {}     # {session_id: {username, created}}


def load_users():
    global _user_db
    if USERS_FILE.exists():
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            _user_db = json.load(f)
        print(f"[auth] 已加载 {len(_user_db)} 个用户")
    return _user_db


def make_session(username):
    sid = hashlib.sha256(
        f"{username}{time.time()}{os.urandom(16)}".encode()
    ).hexdigest()[:32]
    _sessions[sid] = {"username": username, "created": time.time()}
    _clean_sessions()
    return sid


def _clean_sessions():
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["created"] > SESSION_TTL]
    for k in expired:
        del _sessions[k]


def verify_password(username, password):
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    for u in _user_db:
        if u["username"] == username and u["password_hash"] == pwd_hash:
            return True
    return False


def get_session_id(handler):
    cookie = handler.headers.get("Cookie", "")
    return cookie.split("sid=")[-1].split(";")[0].strip()


def require_auth(handler):
    sid = get_session_id(handler)
    if sid and sid in _sessions:
        _sessions[sid]["created"] = time.time()
        return _sessions[sid]["username"]
    return None


def remove_session(sid):
    if sid in _sessions:
        del _sessions[sid]


def user_count():
    return len(_user_db)


# 启动时加载用户
load_users()