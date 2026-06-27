# 志愿Agent 会话系统重构计划

> 目标：将当前单文件前端 + 简易对话存储，重构为适合"高考志愿录取咨询 Agent"的多会话、多消息、可长期保存的系统。
> 核心原则：会话独立、画像独立、消息分页、长对话摘要、知识库来源可追踪、流式输出稳定、前后端职责清晰。

---

## 一、数据库设计（7张新表）

### 1. `users` — 用户管理

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| username | TEXT UNIQUE NOT NULL | 用户名（与现有 users.json 一致） |
| password_hash | TEXT NOT NULL | SHA-256 密码哈希 |
| created_at | REAL | 注册时间 |
| last_login_at | REAL | 最后登录时间 |
| is_active | INTEGER DEFAULT 1 | 账号是否激活 |

**迁移**：从 `data/users.json` 导入现有用户到 `conversations.db`（或新建 `users.db`）。

### 2. `conversations` — 会话管理

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| user_id | TEXT NOT NULL | 关联 users.username |
| session_id | TEXT UNIQUE NOT NULL | UUID，前端展示用 |
| title | TEXT DEFAULT '' | 会话标题 |
| pinned | INTEGER DEFAULT 0 | 置顶标记 |
| archived | INTEGER DEFAULT 0 | 归档标记 |
| deleted_at | REAL | 软删除时间，NULL 表示未删除 |
| created_at | REAL | 创建时间 |
| updated_at | REAL | 最后消息时间 |
| message_count | INTEGER DEFAULT 0 | 消息总数 |

**索引**：`(user_id, pinned, updated_at DESC)` 用于列表排序

### 3. `messages` — 消息存储

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| conversation_id | INTEGER NOT NULL | FK -> conversations.id |
| role | TEXT NOT NULL | user / assistant / system / tool |
| content | TEXT NOT NULL | 消息内容 |
| status | TEXT DEFAULT 'done' | done / streaming / error |
| created_at | REAL | 创建时间 |
| sequence | INTEGER NOT NULL | 在会话中的顺序 |

**索引**：`(conversation_id, sequence)` 用于分页加载

### 4. `message_chunks` — 流式分片

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| message_id | INTEGER NOT NULL | FK -> messages.id |
| chunk_index | INTEGER NOT NULL | 分片顺序 |
| content | TEXT NOT NULL | 分片内容 |
| created_at | REAL | 接收时间 |

### 5. `conversation_summaries` — 会话摘要

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| conversation_id | INTEGER NOT NULL | FK -> conversations.id |
| summary | TEXT NOT NULL | 摘要内容 |
| message_range_start | INTEGER | 覆盖的消息起始 sequence |
| message_range_end | INTEGER | 覆盖的消息结束 sequence |
| created_at | REAL | 生成时间 |

### 6. `candidate_profiles` — 考生画像（每会话独立）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| conversation_id | INTEGER UNIQUE NOT NULL | FK -> conversations.id，一会话一画像 |
| province | TEXT | 省份 |
| year | INTEGER | 高考年份 |
| score | INTEGER | 分数 |
| rank | INTEGER | 全省位次 |
| subject | TEXT | 选科（物理类/历史类/文科/理科） |
| family_condition | TEXT | 家庭条件 |
| region_pref | TEXT JSON | 地域偏好 |
| region_avoid | TEXT JSON | 地域回避 |
| major_pref | TEXT JSON | 专业偏好 |
| school_pref | TEXT JSON | 学校偏好 |
| risk_preference | TEXT | 风险偏好（冲/稳/保） |
| budget_pref | TEXT | 学费预算偏好 |
| career_goal | TEXT | 职业目标 |
| raw_json | TEXT | 原始提取 JSON |
| created_at | REAL | 创建时间 |
| updated_at | REAL | 更新时间 |

### 7. `message_sources` — 知识库来源追踪

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| message_id | INTEGER NOT NULL | FK -> messages.id |
| source_type | TEXT NOT NULL | db / kb / web / tavily |
| source_path | TEXT | 文件路径或 URL |
| source_title | TEXT | 来源标题 |
| snippet | TEXT | 内容片段 |
| score | REAL | 检索相关度分数 |
| created_at | REAL | 创建时间 |

---

## 二、后端架构重构

### 新增文件结构

```
backend/
├── repo/                          # 数据库仓库层
│   ├── __init__.py
│   ├── db.py                      # 数据库连接、初始化、迁移
│   ├── conversation_repo.py       # conversations 表 CRUD
│   ├── message_repo.py            # messages + message_chunks CRUD
│   ├── profile_repo.py            # candidate_profiles CRUD
│   ├── summary_repo.py            # conversation_summaries CRUD
│   └── source_repo.py             # message_sources CRUD
├── service/                       # 业务逻辑层
│   ├── __init__.py
│   ├── conversation_service.py    # 会话管理（创建、重命名、删除、归档、置顶、列表分页）
│   ├── message_service.py         # 消息保存、分页加载、滚动加载历史
│   ├── profile_service.py         # 考生画像抽取和更新
│   ├── summary_service.py         # 长会话摘要生成和管理
│   ├── context_service.py         # 组装 LLM 上下文（画像+摘要+历史消息+知识库）
│   ├── agent_service.py           # 高考志愿 Agent 主流程
│   └── kb_service.py              # 知识库检索（整合现有 kb_search.py）
├── llm/                           # LLM 调用层
│   ├── __init__.py
│   └── llm_service.py             # 大模型流式调用（整合现有 llm_proxy.py）
├── config.py                      # 保持不变
├── auth.py                        # 保持不变
├── models.py                      # 保持不变
├── database.py                    # 保持不变（录取数据查询）
├── recommender.py                 # 保持不变
├── web_search.py                  # 保持不变
├── conversations.py               # 标记为废弃，迁移到 repo/ + service/
├── kb_search.py                   # 标记为废弃，迁移到 service/kb_service.py
├── llm_proxy.py                   # 标记为废弃，迁移到 llm/llm_service.py
├── server.py                      # 重构路由，对接新的 service 层
└── main.py                        # 更新初始化逻辑
```

### 关键流程

#### 2.1 会话管理流程

1. **创建会话**：`POST /api/conversations` → `conversation_service.create()` → 插入 conversations 表，返回 session_id
2. **重命名**：`PUT /api/conversations/{session_id}` → 更新 title
3. **删除**：`DELETE /api/conversations/{session_id}` → 软删除（设 deleted_at）
4. **置顶**：`PATCH /api/conversations/{session_id}/pin` → 切换 pinned 标记
5. **归档**：`PATCH /api/conversations/{session_id}/archive` → 切换 archived 标记
6. **列表**：`GET /api/conversations?page=N&limit=50&search=关键词` → 分页查询，置顶在前，未归档优先
7. **搜索**：侧边栏搜索框，按 title 和最后消息内容模糊匹配

#### 2.2 消息流程

1. **加载消息**：`GET /api/conversations/{session_id}/messages?cursor=sequence&limit=30` → 返回最近 30 条
2. **滚动加载**：用户向上滚动到顶部 → 用 cursor（当前最早消息的 sequence）加载更早的消息
3. **发送消息**：`POST /api/chat` → 保存用户消息 → 创建 assistant 消息（status=streaming）→ SSE 流式返回
4. **流式完成**：合并 message_chunks → 更新 assistant 消息 status=done
5. **流式失败**：更新 status=error，前端恢复按钮状态

#### 2.3 Agent 主流程

```
用户发送消息
  ↓
1. profile_service.update() — 从消息更新考生画像
  ↓
2. context_service.build() — 组装 LLM 上下文：
   - 当前用户问题
   - 会话考生画像（candidate_profiles）
   - 会话滚动摘要（conversation_summaries，如果有）
   - 最近 8-12 轮消息
   - 相关历史消息（向量检索，可选）
   - 本地知识库检索结果（kb_service）
   - Tavily 搜索结果（web_search）
  ↓
3. agent_service.execute() — 调用 LLM 流式生成
  ↓
4. message_service.save_chunks() — 实时保存分片
  ↓
5. message_service.complete() — 合并为完整消息
  ↓
6. source_service.save() — 记录知识库来源
  ↓
7. summary_service.check() — 检查是否需要生成摘要
```

#### 2.4 长会话摘要

触发条件（满足任一即触发）：
- 会话消息数 > 20 条
- 未摘要的消息总字数 > 8000
- 距离上次摘要后新增消息 > 10 条

流程：
1. 取出未摘要的消息范围
2. 调用 LLM 生成摘要（prompt：总结这段对话中的关键信息，包括考生条件、已推荐的学校和专业、用户的反馈和偏好变化）
3. 存入 conversation_summaries
4. 后续构建上下文时，用摘要 + 最近消息替代完整历史

---

## 三、前端重构

### 文件结构

```
frontend/
├── index.html                     # 主页面（纯 HTML 骨架）
├── css/
│   ├── layout.css                 # 整体布局
│   ├── chat.css                   # 消息气泡、输入框等
│   └── responsive.css             # 响应式适配
├── js/
│   ├── app.js                     # 初始化、认证、全局状态
│   ├── conversation.js            # 会话管理（创建、切换、删除、置顶、列表分页）
│   ├── message.js                 # 消息渲染、分页加载、滚动加载历史
│   ├── send.js                    # 发送消息、构建请求
│   ├── stream.js                  # SSE 流式接收和渲染
│   ├── layout-resize.js           # 拖拽调整尺寸
│   └── sidebar.js                 # 侧边栏交互（搜索、新建、删除、置顶）
```

### localStorage 只保存

- `zf_sid` — 会话 cookie
- `zf_active` — 当前会话 ID
- `zf_dark` — 主题
- `xuefeng.sidebar.width` — 侧边栏宽度
- `xuefeng.input.height` — 输入区高度

**不保存**：会话列表、消息内容、考生画像

### 关键交互

1. **进入会话**：从数据库加载最近 30 条消息，显示在聊天区
2. **滚动到顶部**：自动加载更早的消息（上拉分页）
3. **发送消息**：调用 `/api/chat`，SSE 流式渲染
4. **切换会话**：保存当前滚动位置，加载新会话的消息
5. **删除会话**：侧边栏 × 按钮 → 确认 → 软删除
6. **置顶会话**：侧边栏右键菜单或长按 → 切换置顶
7. **搜索会话**：侧边栏顶部搜索框 → 实时过滤

---

## 四、实施步骤

### Phase 1：数据库层（基础）

1. 在 `conversations.db` 创建 7 张新表（兼容现有 conversations + messages 表）
2. 编写 `repo/db.py` — 数据库连接、初始化、迁移工具
3. 编写 6 个 repo 文件 — 每张表的 CRUD
4. 从 `data/users.json` 导入现有用户到 users 表
5. 将现有 conversations/messages 数据迁移到新 schema

### Phase 2：业务逻辑层

6. `conversation_service.py` — 会话 CRUD + 分页列表
7. `message_service.py` — 消息保存 + 分页加载
8. `profile_service.py` — 考生画像抽取（复用现有 /api/extract）
9. `kb_service.py` — 整合现有 kb_search.py
10. `summary_service.py` — 长会话摘要
11. `context_service.py` — 组装 LLM 上下文
12. `llm_service.py` — 整合现有 llm_proxy.py
13. `agent_service.py` — Agent 主流程串联

### Phase 3：API 路由

14. 重构 `server.py` — 对接新的 service 层
15. 新增 API 路由：
    - `GET /api/conversations?page=&limit=&search=` — 会话列表
    - `POST /api/conversations` — 创建会话
    - `PUT /api/conversations/:id` — 重命名
    - `DELETE /api/conversations/:id` — 删除
    - `PATCH /api/conversations/:id/pin` — 置顶
    - `PATCH /api/conversations/:id/archive` — 归档
    - `GET /api/conversations/:id/messages?cursor=&limit=` — 消息分页
    - `GET /api/conversations/:id/profile` — 获取考生画像
    - `GET /api/conversations/:id/sources?message_id=` — 获取消息来源
    - `POST /api/chat` — 重构为使用 agent_service
16. 保持向后兼容 — 旧路由仍然可用

### Phase 4：前端适配

17. 拆分前端 JS 文件
18. 会话列表改为从 API 加载（不再从 localStorage）
19. 消息加载改为分页 API 调用
20. 流式输出对接新的 SSE 格式
21. 侧边栏增加搜索、置顶、删除功能
22. 滚动加载历史消息
23. 移除 localStorage 中的会话和消息存储

### Phase 5：测试和清理

24. 测试会话创建、切换、删除
25. 测试消息分页加载
26. 测试流式输出
27. 测试长会话摘要
28. 测试考生画像独立性
29. 清理废弃文件（conversations.py, kb_search.py, llm_proxy.py）
30. 更新 CLAUDE.md

---

## 五、风险控制

- **数据迁移**：先在测试环境验证迁移脚本，确保现有对话数据不丢失
- **向后兼容**：旧 API 路由保留，新路由并行运行，逐步切换
- **增量实施**：每个 phase 独立可运行，不追求一次性完成
- **回滚方案**：保留旧文件备份，数据库迁移前备份 conversations.db