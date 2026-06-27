#!/usr/bin/env python3
"""志愿Agent — 组装 LLM 上下文服务"""
import json
from .profile_service import get_profile, build_context_string
from .summary_service import get_full_summary
from .message_service import get_recent_for_context
from .kb_service import search as kb_search
from ..database import DB_AVAILABLE, search_admissions
from ..web_search import web_search as tavily_web_search


def build_context(user_message, conv_id, profile=None):
    """组装完整的 LLM 上下文
    返回 (messages_list, sources_list)
    """
    sources = []

    # 1. 获取画像
    if profile is None:
        profile = get_profile(conv_id)
    profile_str = build_context_string(profile)

    # 2. 获取会话摘要
    summary_str = get_full_summary(conv_id)

    # 3. 获取最近消息
    recent_msgs = get_recent_for_context(conv_id, limit=12)

    # 4. 知识库检索
    kb_results = kb_search(user_message, top_k=5)
    kb_context = ""
    if kb_results:
        kb_parts = []
        for path, title, snippet, score in kb_results[:3]:
            if snippet:
                kb_parts.append(f"[{title}]({path}, score={score:.1f})\n{snippet[:400]}")
                sources.append({
                    'source_type': 'kb',
                    'source_path': path,
                    'source_title': title,
                    'snippet': snippet[:200],
                    'score': score,
                })
        kb_context = '\n\n---\n'.join(kb_parts)

    # 5. 联网搜索（如果画像有省份和位次）
    web_context = ""
    if profile and profile.get('province') and profile.get('rank'):
        search_query = (
            f"{profile.get('province', '')} {profile.get('rank', '')}位次 "
            f"{_subject_short(profile.get('subject', ''))} 2025 志愿填报"
        )
        try:
            web_results = tavily_web_search(search_query)
            if web_results:
                web_parts = []
                for r in web_results[:5]:
                    snippet_text = r[:300] if isinstance(r, str) else str(r)[:300]
                    web_parts.append(snippet_text)
                    sources.append({
                        'source_type': 'tavily',
                        'source_path': '',
                        'source_title': snippet_text[:50],
                        'snippet': snippet_text[:200],
                        'score': 0.0,
                    })
                web_context = '\n'.join(web_parts)
        except Exception:
            pass

    # 组装参考资料
    reference_parts = []
    if profile_str:
        reference_parts.append(f"【考生画像】\n{profile_str}")
    if summary_str:
        reference_parts.append(f"【历史对话摘要】\n{summary_str}")
    if kb_context:
        reference_parts.append(f"【知识库参考】\n{kb_context}")
    if web_context:
        reference_parts.append(f"【联网搜索·仅供参考】\n{web_context}")

    # 构建消息列表
    messages = []
    if reference_parts:
        messages.append({
            'role': 'system',
            'content': '【参考资料，请基于这些数据给出建议】\n\n' + '\n\n'.join(reference_parts)
        })

    # 添加最近对话
    for msg in recent_msgs:
        content = msg['content']
        # 截断过长的消息
        if len(content) > 2000:
            content = content[:2000] + '...(内容过长已截断)'
        messages.append({'role': msg['role'], 'content': content})

    return messages, sources


def _subject_short(subject):
    """选科简称"""
    if '物理' in str(subject):
        return '物理类'
    elif '历史' in str(subject):
        return '历史类'
    return ''