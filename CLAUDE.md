# CLAUDE.md

思考过程和回答使用中文

## 项目概述

志愿Agent 是一个高考志愿填报 AI 助手，纯 Python 标准库 + 零前端框架，Windows 优先部署。

## 启动方式

```bash
# 方式1：直接启动
python run.py

# 方式2：批处理启动
启动.bat

# 服务地址：http://127.0.0.1:8765
# 快捷入口：打开我.html
```

## 目录结构

```
志愿agent/
├── run.py              # 启动入口
├── 启动.bat            # Windows 启动脚本（自动建虚拟环境）
├── 打开我.html         # 快捷入口页面
├── backend/            # 后端模块包
│   ├── __init__.py
│   ├── config.py       # 全局配置与路径常量
│   ├── models.py       # AI 模型配置、健康检查、多模型路由
│   ├── auth.py         # 用户认证与会话管理
│   ├── kb_search.py    # 知识仓库关键词搜索（按业务语义分类）
│   ├── database.py     # 数据库操作（初始化、查询、自定义 Excel）
│   ├── web_search.py   # 联网搜索（Tavily + 百度兜底）
│   ├── recommender.py  # 冲稳保三档推荐引擎
│   ├── llm_proxy.py    # LLM 调用（多模型路由、SSE 流式）
│   ├── server.py       # HTTP 请求处理器（路由、CORS、认证）
│   ├── conversations.py # 对话数据库（存储、查询、删除会话和消息）
│   ├── main.py         # 服务器启动逻辑
│   └── kb_skill.md     # 知识库调用指南
├── frontend/
│   └── index.html      # 前端单页应用（含登录、聊天、对话持久化）
├── data/               # 数据文件
│   ├── users.json      # 用户账号（SHA-256 哈希）
│   ├── ai_config.json  # AI 配置（多模型路由）
│   ├── 用户账号.xlsx   # 明文账号（分发给用户）
│   ├── 用户数据表.xlsx  # 自定义填报数据
│   ├── gen_users.py    # 账号生成脚本
│   ├── gaokao_data.db  # SQLite 录取数据库（首次启动自动从 kb/ 复制）
│   └── conversations.db # 对话数据库（自动创建）
└── kb/                 # 知识仓库（markdown 文件，按分类目录组织）
```

## 后端架构

- **HTTP 服务器**: `ThreadingHTTPServer` 监听 8765 端口
- **用户认证**: Cookie-based session，24 小时 TTL，SHA-256 密码哈希
- **AI 配置**: 从 `data/ai_config.json` 加载多模型路由，endpoint 包含完整 URL
- **模型路由**: 健康检查（60s 间隔），自动故障切换
- **数据库**: SQLite 双 schema 兼容（v1: `admission` 表，v2: `major_scores` 表）
- **推荐引擎**: "冲稳保"三档推荐，渐进式回退
- **知识仓库**: 按业务语义分类检索（01-08 为核心目录）
- **联网搜索**: Tavily AI Search（主）+ 百度搜索正则解析（兜底）
- **LLM 代理**: OpenAI 兼容 API，SSE 流式传输，兼容 `reasoning_content`
- **对话持久化**: SQLite 独立数据库存储用户会话和消息

### 模块依赖关系

```
config.py (无依赖)
    └── models.py (依赖 config)
    └── auth.py (依赖 config)
    └── kb_search.py (依赖 config)
    └── database.py (依赖 config)
        └── recommender.py (依赖 config, database)
    └── web_search.py (依赖 models)
    └── llm_proxy.py (依赖 models)
    └── conversations.py (依赖 config)
    └── server.py (依赖所有模块)
        └── main.py (依赖 config, server, database, kb_search, models, auth)
```

### API 路由

| 方法 | 路径                     | 认证 | 功能                                          |
| ---- | ------------------------ | ---- | --------------------------------------------- |
| GET  | `/`                      | 无   | 主页面 HTML                                   |
| GET  | `/health`                | 无   | 健康检查                                      |
| GET  | `/config`                | 无   | 服务端配置                                    |
| POST | `/login`                 | 无   | 用户登录                                      |
| POST | `/logout`                | 无   | 退出登录                                      |
| POST | `/api/chat`              | 是   | LLM 聊天（SSE 流式，自动保存对话）            |
| POST | `/api/extract`           | 是   | AI 信息提取                                   |
| POST | `/api/tavily`            | 是   | Tavily 搜索                                   |
| POST | `/api/conversations`     | 是   | 对话管理（list/save）                         |
| POST | `/api/conversations/delete` | 是 | 删除对话                                      |
| POST | `/api/messages/load`     | 是   | 加载消息                                      |
| GET  | `/recommend`             | 是   | 冲稳保推荐                                    |
| GET  | `/query`                 | 是   | 通用数据库查询                                |
| GET  | `/search`                | 是   | 联网搜索                                      |
| GET  | `/db_stats`              | 是   | 数据库统计                                    |
| GET  | `/kb_search`             | 是   | 知识仓库搜索                                  |
| GET  | `/userdata`              | 是   | 自定义 Excel 数据                             |
| GET  | `/reload_userdata`       | 是   | 重新加载自定义数据                            |

## 前端架构 (`frontend/index.html`)

- **单文件 SPA**: 零框架，原生 HTML/CSS/JS
- **登录认证**: 登录页 + localStorage 持久化 + 自动登录
- **数据管线**: 用户发送消息 → AI 提取 → DB 查询 → KB 搜索 → 联网搜索 → LLM 生成
- **聊天**: 多对话管理，SSE 流式响应，自动同步到数据库
- **移动端**: 响应式设计，侧边栏滑入抽屉
- **深色模式**: 一键切换，localStorage 持久化

## AI 配置 (`data/ai_config.json`)

```json
{
  "models": [
    {"name": "模型名", "endpoint": "完整API地址(含/v1/chat/completions)", "token": "密钥", "priority": 1}
  ],
  "tavily_search_key": "Tavily API 密钥",
  "health_check_interval": 60,
  "timeout_seconds": 10,
  "max_retries": 2
}
```

## 知识库 (`kb/`)

按业务语义分类检索，核心目录为 01-08：
- 01_政策规则、02_省份数据、03_院校库、04_专业库
- 05_张雪峰风格库、06_案例库、07_录取数据、08_提示词模板

## 注意事项

- 服务器使用 `HttpOnly` cookie，CORS 使用 origin 反射
- `escapeHtml` 使用数值 HTML 实体
- Windows 控制台默认 GBK 编码，`sys.stdout.reconfigure(encoding="utf-8")` 已处理
- 数据库文件有 KB 源副本，启动时自动复制到 `data/`
- 对话数据库（`data/conversations.db`）自动创建
- 所有后端模块使用相对导入，通过 `run.py` 启动