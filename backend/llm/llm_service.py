#!/usr/bin/env python3
"""志愿Agent — LLM 流式调用服务（整合 llm_proxy）"""
from ..llm_proxy import invoke_llm, call_llm_with_routing, extract_user_info


def stream_chat(messages, temp=0.7, token_limit=None, on_chunk=None):
    """流式聊天调用
    :returns: 完整文本
    """
    return invoke_llm(messages, temp=temp, token_limit=token_limit, on_chunk=on_chunk)


def non_stream_chat(messages, temp=0.7, token_limit=None):
    """非流式聊天调用"""
    return invoke_llm(messages, temp=temp, token_limit=token_limit)


def extract(text):
    """从文本中提取用户信息"""
    return extract_user_info(text)


__all__ = ['stream_chat', 'non_stream_chat', 'extract']