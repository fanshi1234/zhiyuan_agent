#!/usr/bin/env python3
"""志愿Agent — 启动脚本"""
import sys
import os

# 确保 backend 包能找到
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.main import start_server

if __name__ == "__main__":
    start_server()