#!/usr/bin/env python3
"""志愿Agent — HTTP 请求处理器：路由、认证、CORS、SSE 流式"""
import json
import re
import threading
import traceback
import urllib.parse
import uuid as uuid_mod
from http.server import BaseHTTPRequestHandler

from .config import TEMPLATE_FILE, LISTEN_PORT
from .auth import require_auth, get_session_id, make_session, verify_password, remove_session, _sessions
from .database import DB_AVAILABLE, search_admissions, province_stats
from .kb_search import kb_search as kb_search_legacy, kb_file_count
from .recommender import build_recommendation
from .web_search import web_search, tavily_query
from .llm_proxy import invoke_llm, extract_user_info
from .models import get_models, get_current_model_idx, LLM_ENDPOINT, LLM_TOKEN, LLM_ENGINE, TAVILY_TOKEN
from .conversations import (
    init_conversations_db,
)

# 新 service 层
from .service.conversation_service import (
    create_conversation as cs_create,
    rename_conversation as cs_rename,
    regenerate_title as cs_regenerate_title,
    pin_conversation as cs_pin,
    archive_conversation as cs_archive,
    delete_conversation as cs_delete,
    get_conversation as cs_get,
    list_user_conversations as cs_list,
    get_conv_id_or_create,
)
from .service.message_service import (
    load_messages as ms_load,
    create_streaming_message as ms_create_streaming,
    complete_message as ms_complete,
    error_message as ms_error,
    append_chunk as ms_append_chunk,
    save_message as ms_save,
)
from .service.profile_service import get_profile as ps_get
from .service.stream_session import StreamingSession
from .repo.source_repo import get_by_message as sources_get
from .repo.conversation_repo import get_conv_id, ensure_exists


class AppHandler(BaseHTTPRequestHandler):

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json;charset=utf-8")
        self._cors_headers()
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin and origin.startswith("http"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")

    def _cors_preflight(self):
        self.send_response(200)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, PATCH, DELETE")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Connection", "close")
        self.end_headers()

    # ---- OPTIONS ----
    def do_OPTIONS(self):
        self._cors_preflight()

    # ---- POST (backward compat + new routes) ----
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"
        body = raw_body.decode("utf-8", errors="replace") if raw_body else "{}"
        path = self.path.split("?")[0]
        auth_routes = ("/api/chat", "/api/extract", "/api/tavily", "/api/conversations")
        route_map = {
            "/login": lambda: self._route_login(body),
            "/logout": lambda: self._route_logout(),
            "/api/chat": lambda: self._route_chat(body),
            "/api/extract": lambda: self._route_extract(body),
            "/api/tavily": lambda: self._route_tavily(body),
            "/api/conversations": lambda: self._route_conversations(body),
            "/api/conversations/delete": lambda: self._route_delete_conversation(body),
            "/api/messages/load": lambda: self._route_load_messages(body),
        }
        # 检查新路由: regenerate-title
        regen_match = re.match(r'^/api/conversations/([^/]+)/regenerate-title$', path)
        if regen_match:
            if not require_auth(self):
                return self._json_response({"error": "未登录"}, 401)
            return self._route_post_regenerate_title(regen_match.group(1), body)
        handler = route_map.get(path)
        if handler:
            if path in auth_routes:
                if not require_auth(self):
                    return self._json_response({"error": "未登录"}, 401)
            handler()
        else:
            self._json_response({"error": "路径不存在"}, 404)

    # ---- PUT/PATCH/DELETE ----
    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?")[0]
        if not require_auth(self):
            return self._json_response({"error": "未登录"}, 401)
        if re.match(r'^/api/conversations/[^/]+$', path):
            return self._route_rename_conversation(raw_body)
        self._json_response({"error": "路径不存在"}, 404)

    def do_PATCH(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?")[0]
        if not require_auth(self):
            return self._json_response({"error": "未登录"}, 401)
        m = re.match(r'^/api/conversations/([^/]+)/pin$', path)
        if m:
            return self._route_patch_conversation_pin(m.group(1), raw_body)
        m = re.match(r'^/api/conversations/([^/]+)/archive$', path)
        if m:
            return self._route_patch_conversation_archive(m.group(1), raw_body)
        m = re.match(r'^/api/conversations/([^/]+)/title$', path)
        if m:
            return self._route_patch_conversation_title(m.group(1), raw_body)
        self._json_response({"error": "路径不存在"}, 404)

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if not require_auth(self):
            return self._json_response({"error": "未登录"}, 401)
        m = re.match(r'^/api/conversations/([^/]+)$', path)
        if m:
            return self._route_delete_conversation_new(m.group(1))
        self._json_response({"error": "路径不存在"}, 404)

    # ---- Static file serving ----
    def _serve_static_file(self, path):
        from .config import FRONTEND_DIR
        import mimetypes
        rel = path.lstrip("/")
        fp = FRONTEND_DIR / rel
        if not fp.is_file():
            return False
        content_type, _ = mimetypes.guess_type(str(fp))
        if not content_type:
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ";charset=utf-8")
        self._cors_headers()
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            with open(fp, "rb") as fh:
                self.wfile.write(fh.read())
        except Exception:
            pass
        return True

    # ---- GET ----
    def do_GET(self):
        path = self.path.split("?")[0]

        # Static files
        if path.startswith("/css/") or path.startswith("/js/"):
            if not self._serve_static_file(path):
                self._json_response({"error": "文件不存在"}, 404)
            return

        if path == "/health":
            return self._route_health()
        if path == "/config":
            return self._route_config()

        if not require_auth(self):
            # 新 API 路由
            if path == "/api/conversations" or path.startswith("/api/conversations/"):
                return self._json_response({"error": "未登录"}, 401)

        # 新 API: 会话列表
        if path == "/api/conversations":
            return self._route_get_conversations()

        # 新 API: 消息分页
        m = re.match(r'^/api/conversations/([^/]+)/messages$', path)
        if m:
            return self._route_get_messages(m.group(1))

        # 新 API: 考生画像
        m = re.match(r'^/api/conversations/([^/]+)/profile$', path)
        if m:
            return self._route_get_profile(m.group(1))

        # 新 API: 消息来源
        m = re.match(r'^/api/conversations/([^/]+)/sources$', path)
        if m:
            return self._route_get_sources()

        # 旧路由
        if path == "/query":
            return self._route_query()
        if path == "/recommend":
            return self._route_recommend()
        if path == "/search":
            return self._route_search()
        if path == "/db_stats":
            return self._route_db_stats()
        if path == "/kb_search":
            return self._route_kb_search()
        if path == "/userdata":
            return self._json_response({"data": get_custom_records(), "count": custom_data_count()})
        if path == "/reload_userdata":
            refresh_custom_data()
            return self._json_response({"ok": True, "count": custom_data_count()})

        # 主页面
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0, no-transform")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as fh:
                self.wfile.write(fh.read().encode("utf-8"))
        except FileNotFoundError:
            self.wfile.write("<h1>模板文件不存在</h1>".encode("utf-8"))

    # ============================================================
    # POST 路由
    # ============================================================

    def _route_login(self, body):
        try:
            data = json.loads(body) if body else {}
            username = data.get("username", "")
            password = data.get("password", "")
            if verify_password(username, password):
                sid = make_session(username)
                self.send_response(200)
                self.send_header("Content-Type", "application/json;charset=utf-8")
                self.send_header("Set-Cookie", f"sid={sid}; Path=/; Max-Age={86400}; HttpOnly")
                self.send_header("Connection", "close")
                self._cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(
                    {"ok": True, "username": username, "session_id": sid},
                    ensure_ascii=False,
                ).encode("utf-8"))
            else:
                self._json_response({"error": "用户名或密码错误"}, 403)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    def _route_logout(self):
        sid = get_session_id(self)
        remove_session(sid)
        self._json_response({"ok": True})

    def _route_chat(self, body):
        """聊天路由 — 使用新的 service 层"""
        data = json.loads(body) if body else {}
        msgs = data.get("messages", [])
        mdl = data.get("model")
        temp = data.get("temperature", 0.7)
        mx_tok = data.get("max_tokens")
        streaming = data.get("stream", False)
        session_id = data.get("session_id", "")
        username = require_auth(self) or ""

        if not username or not session_id:
            if streaming:
                return
            return self._json_response({"error": "参数错误"}, 400)

        # 获取或创建会话
        conv_id = get_conv_id(username, session_id)
        if conv_id is None:
            from .service.conversation_service import get_or_create
            session_id, conv_id = get_or_create(username, session_id)

        # 保存用户消息（取最后一条 user 消息）
        last_user = None
        for m in reversed(msgs):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break
        if last_user:
            try:
                ms_save(username, session_id, conv_id, "user", last_user)
            except Exception:
                pass
            # 异步提取画像 — 不阻塞响应
            def _async_profile(cid, msg):
                try:
                    from .service.profile_service import update_profile_from_message
                    update_profile_from_message(cid, msg)
                except Exception:
                    pass
            threading.Thread(target=_async_profile, args=(conv_id, last_user), daemon=True).start()

        if streaming:
            _handle_streaming_chat(self, msgs, mdl, temp, mx_tok, username, session_id, conv_id)
        else:
            try:
                reply = invoke_llm(msgs, mdl, temp, mx_tok)
                self._json_response({"choices": [{"message": {"content": reply}}]})

                # 保存助手回复
                if conv_id:
                    try:
                        ms_save(username, session_id, conv_id, "assistant", reply or "")
                    except Exception:
                        pass
            except Exception as exc:
                self._json_response({"error": str(exc)}, 500)
    def _route_extract(self, body):
        try:
            data = json.loads(body) if body else {}
            text = data.get("text", "")
            info = extract_user_info(text)
            if info:
                self._json_response(info)
            else:
                self._json_response({"error": "提取失败"})
        except Exception as exc:
            self._json_response({
                "province": "", "rank": 0, "score": 0, "subject": "",
                "majors": [], "schools": [], "keywords": [], "error": str(exc),
            })
    
    def _route_tavily(self, body):
        try:
            if isinstance(body, bytes):
                try:
                    data = json.loads(body.decode("utf-8"))
                except Exception:
                    data = json.loads(body.decode("utf-8", errors="replace"))
            else:
                data = json.loads(body) if body else {}
            query_text = data.get("query", "")
            count = int(data.get("n", 5))
            results = tavily_query(query_text, count)
            self._json_response({"results": results or []})
        except Exception as exc:
            self._json_response({"results": [], "error": str(exc)})
    
    # ============================================================
    # 新 API 路由 — 会话管理
    # ============================================================
    
    def _route_get_conversations(self):
        """GET /api/conversations?page=&limit=&search=&archived="""
        try:
            username = require_auth(self) or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            page = int(qs.get("page", ["1"])[0])
            limit = int(qs.get("limit", ["50"])[0])
            search = qs.get("search", [""])[0]
            archived = qs.get("archived", [""])[0].lower() == "true"
            result = cs_list(username, page, limit, search, archived)
            self._json_response(result)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_create_conversation(self, body):
        """POST /api/conversations (新格式)"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            title = data.get("title", "")
            session_id = data.get("session_id")
            result_session_id, conv_id = cs_create(username, title, session_id=session_id)
            self._json_response({"ok": True, "session_id": result_session_id, "conv_id": conv_id})
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_rename_conversation(self, body):
        """PUT /api/conversations/:session_id"""
        try:
            username = require_auth(self) or ""
            parts = self.path.split("?")[0].split("/")
            session_id = parts[3] if len(parts) > 3 else ""
            data = json.loads(body) if body else {}
            title = data.get("title", "")
            result = cs_rename(username, session_id, title)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 404)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_patch_conversation_pin(self, session_id, body):
        """PATCH /api/conversations/:session_id/pin"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            pinned = data.get("pinned", True)
            result = cs_pin(username, session_id, pinned)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 404)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_patch_conversation_archive(self, session_id, body):
        """PATCH /api/conversations/:session_id/archive"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            archived = data.get("archived", True)
            result = cs_archive(username, session_id, archived)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 404)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    def _route_patch_conversation_title(self, session_id, body):
        """PATCH /api/conversations/:session_id/title — 手动重命名（锁定标题）"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            title = data.get("title", "")
            result = cs_rename(username, session_id, title)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 400)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    def _route_post_regenerate_title(self, session_id, body):
        """POST /api/conversations/:session_id/regenerate-title — 重新生成标题"""
        try:
            username = require_auth(self) or ""
            conv_id = get_conv_id(username, session_id)
            if conv_id is None:
                return self._json_response({"error": "会话不存在"}, 404)
            # 获取当前画像
            profile = ps_get(conv_id)
            # 获取最近一条用户消息
            from .service.message_service import get_last_user_message
            last_msg = get_last_user_message(username, session_id, conv_id) or ""
            # 生成标题
            from .service.title_service import try_auto_title
            new_title = try_auto_title(last_msg, profile)
            if not new_title:
                return self._json_response({"error": "信息不足，无法生成标题"}, 400)
            result = cs_regenerate_title(username, session_id, new_title)
            self._json_response(result)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_delete_conversation_new(self, session_id):
        """DELETE /api/conversations/:session_id"""
        try:
            username = require_auth(self) or ""
            result = cs_delete(username, session_id)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 404)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_get_messages(self, session_id):
        """GET /api/conversations/:session_id/messages?cursor=&limit="""
        try:
            username = require_auth(self) or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cursor = qs.get("cursor", [None])[0]
            if cursor is not None:
                cursor = int(cursor)
            limit = int(qs.get("limit", ["30"])[0])
            conv_id = get_conv_id(username, session_id)
            if conv_id is None:
                return self._json_response({"error": "会话不存在"}, 404)
            result = ms_load(username, session_id, conv_id, cursor, limit)
            self._json_response(result)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_get_profile(self, session_id):
        """GET /api/conversations/:session_id/profile"""
        try:
            username = require_auth(self) or ""
            conv_id = get_conv_id(username, session_id)
            if conv_id is None:
                return self._json_response({"error": "会话不存在"}, 404)
            profile = ps_get(conv_id)
            self._json_response({"profile": profile})
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def _route_get_sources(self):
        """GET /api/conversations/:session_id/sources?message_id="""
        try:
            username = require_auth(self) or ""
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            message_id = qs.get("message_id", [None])[0]
            if message_id is None:
                return self._json_response({"error": "需要 message_id"}, 400)
            sources = sources_get(int(message_id))
            self._json_response({"sources": sources})
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    # ============================================================
    # 旧路由（保持向后兼容）
    # ============================================================
    
    def _route_health(self):
        models = get_models()
        cur_idx = get_current_model_idx()
        return self._json_response({
            "ok": True,
            "database": DB_AVAILABLE,
            "models": [
                {"name": m["name"], "latency_ms": round(m["latency_ms"], 0) if m["latency_ms"] else None,
                 "failed": m["failed"], "current": models.index(m) == cur_idx}
                for m in models
            ],
        })
    
    def _route_config(self):
        username = require_auth(self)
        models = get_models()
        cur_idx = get_current_model_idx()
        return self._json_response({
            "llm_configured": bool(LLM_TOKEN),
            "tavily_configured": bool(TAVILY_TOKEN),
            "model": LLM_ENGINE,
            "tavily_key": TAVILY_TOKEN,
            "endpoint": LLM_ENDPOINT,
            "username": username or "",
            "kb_files": kb_file_count(),
            "models": [
                {"name": m["name"], "endpoint": m["endpoint"], "priority": m["priority"],
                 "latency_ms": round(m["latency_ms"], 0) if m["latency_ms"] else None,
                 "failed": m["failed"], "current": models.index(m) == cur_idx}
                for m in models
            ],
        })
    
    def _route_query(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rows = search_admissions(
            qs.get("province", [""])[0], qs.get("school", [""])[0], qs.get("major", [""])[0])
        return self._json_response({"data": rows, "count": len(rows) if rows else 0})
    
    def _route_recommend(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        prov = qs.get("province", [""])[0]
        keyword = qs.get("keyword", [""])[0]
        subj = qs.get("subject", [""])[0]
        try:
            rank_val = int(qs.get("rank", ["0"])[0])
        except (ValueError, IndexError):
            rank_val = 0
        try:
            score_val = int(qs.get("score", ["0"])[0])
        except (ValueError, IndexError):
            score_val = 0
        if prov and (rank_val > 0 or score_val > 0):
            result = build_recommendation(prov, rank_val, score_val, keyword, subj)
            if result:
                return self._json_response(result)
        return self._json_response({"error": "需要省份和位次或分数"}, 400)
    
    def _route_search(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q = qs.get("q", [""])[0]
        if q:
            results = web_search(q)
            return self._json_response({"results": results})
        return self._json_response({"results": []})
    
    def _route_db_stats(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        prov = qs.get("province", [""])[0]
        return self._json_response(province_stats(prov))
    
    def _route_kb_search(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q = qs.get("q", [""])[0]
        results = kb_search_legacy(q)
        return self._json_response({"results": results, "count": len(results)})
    
    # ============================================================
    # 旧对话路由（向后兼容）
    # ============================================================
    
    def _route_conversations(self, body):
        """旧兼容路由 — 统一转发到新 service 层"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            action = data.get("action")

            if action is None and data.get("session_id"):
                return self._route_create_conversation(body)
            if action is None:
                action = "list"

            if action == "list":
                # 转发到新 service 层
                result = cs_list(username, 1, 200)
                return self._json_response(result)
            elif action == "save":
                session_id = data.get("session_id", "")
                title = data.get("title", "")
                # 转发到新 service 层创建/更新
                existing = get_conv_id(username, session_id)
                if existing:
                    return self._json_response(cs_rename(username, session_id, title))
                else:
                    sid, cid = cs_create(username, title, session_id=session_id)
                    return self._json_response({"ok": True})
            else:
                return self._json_response({"error": "未知操作"})
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    def _route_delete_conversation(self, body):
        """旧兼容路由 — 改为软删除"""
        try:
            username = require_auth(self) or ""
            data = json.loads(body) if body else {}
            session_id = data.get("session_id", "")
            # 转发到新 service 层（软删除）
            result = cs_delete(username, session_id)
            self._json_response(result)
        except ValueError as e:
            self._json_response({"error": str(e)}, 404)
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)

    def _route_load_messages(self, body):
        """旧兼容路由 — 分页加载（默认最近30条）"""
        try:
            data = json.loads(body) if body else {}
            session_id = data.get("session_id", "")
            username = require_auth(self) or ""
            conv_id = get_conv_id(username, session_id)
            if conv_id is None:
                return self._json_response({"messages": []})
            # 转发到新 service 层（分页加载）
            result = ms_load(username, session_id, conv_id, None, 30)
            self._json_response({"messages": result["messages"]})
        except Exception as exc:
            self._json_response({"error": str(exc)}, 500)
    
    def log_message(self, fmt, *args):
        msg = fmt % args if args else fmt
        if any(ep in msg for ep in ["/recommend", "/query", "/health", "/search", "/api/", "/login", "/kb_search"]):
            print(f"[HTTP] {msg}")

def _sse_event(payload):
    """将字典序列化为 SSE 事件"""
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _handle_streaming_chat(handler, msgs, mdl, temp, mx_tok, username, session_id, conv_id):
    """流式响应 — 统一 JSON SSE 协议"""
    req_id = uuid_mod.uuid4().hex[:8]
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler._cors_headers()
    handler.end_headers()

    stream = StreamingSession(username, session_id, conv_id)
    msg_id = stream.start()

    print(f"[{req_id}] stream_start conv={conv_id} msg={msg_id}")

    # 发送 start 事件
    try:
        handler.wfile.write(_sse_event({
            "type": "start",
            "conversation_id": conv_id,
            "message_id": str(msg_id),
        }))
        handler.wfile.flush()
    except Exception:
        print(f"[{req_id}] client disconnected on start")
        return

    reply_parts = []
    reasoning_parts = []
    chunk_count = 0
    error_occurred = None

    def write_chunk(text, is_reasoning=False):
        nonlocal chunk_count
        chunk_count += 1
        if is_reasoning:
            reasoning_parts.append(text)
            try:
                handler.wfile.write(_sse_event({
                    "type": "reasoning",
                    "conversation_id": conv_id,
                    "message_id": str(msg_id),
                    "content": text,
                }))
                handler.wfile.flush()
            except Exception:
                raise
        else:
            reply_parts.append(text)
            try:
                handler.wfile.write(_sse_event({
                    "type": "chunk",
                    "conversation_id": conv_id,
                    "message_id": str(msg_id),
                    "content": text,
                }))
                handler.wfile.flush()
            except Exception:
                raise
            try:
                stream.append(text)
            except Exception:
                pass

    try:
        invoke_llm(msgs, mdl, temp, mx_tok, on_chunk=write_chunk)
        total_len = sum(len(c) for c in reply_parts)
        reasoning_len = sum(len(c) for c in reasoning_parts)
        stream.complete()
        if chunk_count == 0:
            print(f"[{req_id}] WARN: LLM returned 0 chunks (no content generated)")
        print(f"[{req_id}] done conv={conv_id} msg={msg_id} chunks={chunk_count} content_chars={total_len} reasoning_chars={reasoning_len}")
    except Exception as e:
        total_len = sum(len(c) for c in reply_parts)
        error_occurred = str(e)
        stream.fail(error_occurred)
        print(f"[{req_id}] error conv={conv_id} msg={msg_id} chars_so_far={total_len}: {e}")
        print("".join(traceback.format_stack()))

    # 发送结束事件
    try:
        if error_occurred:
            handler.wfile.write(_sse_event({
                "type": "error",
                "conversation_id": conv_id,
                "message_id": str(msg_id),
                "message": error_occurred,
            }))
        else:
            handler.wfile.write(_sse_event({
                "type": "done",
                "conversation_id": conv_id,
                "message_id": str(msg_id),
                "reasoning_length": sum(len(c) for c in reasoning_parts),
            }))
        handler.wfile.flush()
    except Exception:
        pass

    handler.close_connection = True

    # 标题生成放到后台线程
    def _async_title():
        try:
            from .service.profile_service import get_profile as ps_get
            from .service.title_service import try_auto_title
            from .service.conversation_service import auto_update_title
            profile = ps_get(conv_id)
            if profile:
                last_user = ""
                for m in reversed(msgs):
                    if m.get("role") == "user":
                        last_user = m.get("content", "")
                        break
                new_title = try_auto_title(last_user, profile)
                if new_title:
                    auto_update_title(username, session_id, new_title)
        except Exception:
            pass
    threading.Thread(target=_async_title, daemon=True).start()

