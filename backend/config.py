#!/usr/bin/env python3
"""志愿Agent — 全局配置与路径常量"""
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
KB_DIR = ROOT_DIR / "kb"
FRONTEND_DIR = ROOT_DIR / "frontend"

DATABASE_FILE = DATA_DIR / "gaokao_data.db"
DATABASE_GZ = DATA_DIR / "gaokao_data.db.gz"
KB_DATABASE_FILE = KB_DIR / "07_录取数据" / "gaokao_data.db"
TEMPLATE_FILE = FRONTEND_DIR / "index.html"
USERS_FILE = DATA_DIR / "users.json"
AI_CONFIG_FILE = DATA_DIR / "ai_config.json"

# 加载 .env 文件（如果存在）
_env_file = ROOT_DIR / ".env"
if _env_file.exists():
    try:
        for line in _env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass

# 服务配置（环境变量优先，向下兼容）
LISTEN_PORT = int(os.getenv("XUEFENG_PORT", "8765"))
SESSION_TTL = int(os.getenv("SESSION_TTL", "86400"))

CHINA_PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
    "青海", "宁夏", "新疆", "内蒙古",
]