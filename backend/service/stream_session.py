#!/usr/bin/env python3
"""志愿Agent — 流式分片服务（供 SSE 流式使用）"""
import time
from ..repo.message_repo import save_chunk, create_streaming, complete_streaming, set_error
from ..repo.conversation_repo import increment_message_count, update_timestamp


class StreamingSession:
    """管理一次流式输出会话"""

    def __init__(self, user_id, session_id, conv_id):
        self.user_id = user_id
        self.session_id = session_id
        self.conv_id = conv_id
        self.msg_id = None
        self.chunks = []
        self.chunk_index = 0
        self.completed = False
        self.failed = False

    def start(self):
        """创建 streaming 消息"""
        self.msg_id = create_streaming(self.conv_id)
        increment_message_count(self.user_id, self.session_id)
        update_timestamp(self.user_id, self.session_id)
        return self.msg_id

    def append(self, text):
        """追加分片"""
        self.chunks.append(text)
        save_chunk(self.msg_id, self.chunk_index, text)
        self.chunk_index += 1
        return text

    def complete(self):
        """完成流式输出"""
        content = ''.join(self.chunks)
        complete_streaming(self.msg_id, content)
        self.completed = True
        return content

    def fail(self, error_msg=""):
        """标记失败"""
        set_error(self.msg_id, error_msg)
        self.failed = True