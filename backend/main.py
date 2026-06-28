#!/usr/bin/env python3
"""志愿Agent — 入口：启动 HTTP 服务器"""
import sys
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from .config import LISTEN_HOST, LISTEN_PORT, ROOT_DIR, DATA_DIR
from .server import AppHandler
from .database import DB_AVAILABLE
from .kb_search import kb_file_count
from .models import get_models, LLM_ENGINE, TAVILY_TOKEN
from .auth import user_count
from .conversations import init_conversations_db
from .repo.db import init_db as init_new_db


def start_server():
    # 确保 data 目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 初始化对话数据库（旧）
    init_conversations_db()
    # 初始化新数据库层（7 张表，自动迁移）
    init_new_db()

    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), AppHandler)
    models = get_models()

    print(f"志愿Agent 服务已启动: http://127.0.0.1:{LISTEN_PORT}/")
    print(f"数据库: {'已加载' if DB_AVAILABLE else '未找到'}")
    print(f"知识仓库: {kb_file_count()} 个文件")
    print(f"大模型: {len(models)} 个模型 (当前: {LLM_ENGINE})")
    for m in models:
        status = "★" if m["name"] == LLM_ENGINE else " "
        print(f"  {status} {m['name']} -> {m['endpoint']}")
    print(f"联网搜索: {'已配置' if TAVILY_TOKEN else '未配置'}")
    print(f"用户数: {user_count()}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n已停止")


if __name__ == "__main__":
    start_server()