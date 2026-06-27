#!/usr/bin/env python3
"""志愿Agent — 高考志愿 Agent 主流程"""
import json
from .conversation_service import get_or_create
from .message_service import save_message, create_streaming_message, complete_message, error_message, append_chunk
from .profile_service import update_profile_from_message
from .context_service import build_context
from .summary_service import check_and_generate
from ..repo.source_repo import save_batch
from ..llm_proxy import invoke_llm, extract_user_info


def chat(user_id, session_id, user_message, on_chunk=None):
    """完整聊天流程
    1. 确保会话存在
    2. 保存用户消息
    3. 更新考生画像
    4. 组装上下文
    5. 创建 assistant 消息（streaming）
    6. 调用 LLM 流式生成
    7. 保存来源
    8. 完成消息
    9. 检查是否需要摘要
    """
    # 1. 确保会话存在
    session_id, conv_id = get_or_create(user_id, session_id)

    # 2. 保存用户消息
    save_message(user_id, session_id, conv_id, "user", user_message)

    # 3. 更新考生画像
    try:
        update_profile_from_message(conv_id, user_message)
    except Exception as e:
        print(f"[agent] 画像更新失败: {e}")

    # 4. 组装上下文
    sys_prompt = _get_system_prompt()
    ctx_messages, sources = build_context(user_message, conv_id)

    # 合并 system prompt
    full_messages = [{"role": "system", "content": sys_prompt}]
    for msg in ctx_messages:
        if msg['role'] == 'system':
            # 合并 system 消息
            if full_messages and full_messages[-1]['role'] == 'system':
                full_messages[-1]['content'] += '\n\n' + msg['content']
            else:
                full_messages.append(msg)
        else:
            full_messages.append(msg)

    # 5. 创建 streaming 消息
    msg_id = create_streaming_message(user_id, session_id, conv_id)

    # 6. 调用 LLM 流式生成
    try:
        full_reply = ""
        chunk_index = 0

        if on_chunk:
            # 流式模式
            def chunk_callback(text):
                nonlocal full_reply, chunk_index
                full_reply += text
                append_chunk(user_id, session_id, conv_id, msg_id, text, chunk_index)
                chunk_index += 1
                on_chunk(text)

            invoke_llm(full_messages, temp=0.7, on_chunk=chunk_callback)
        else:
            # 非流式模式
            full_reply = invoke_llm(full_messages, temp=0.7) or ""

        # 7. 保存来源
        if sources:
            save_batch(msg_id, sources)

        # 8. 完成消息
        complete_message(msg_id, full_reply)

        # 9. 检查是否需要摘要
        try:
            check_and_generate(conv_id)
        except Exception as e:
            print(f"[agent] 摘要检查失败: {e}")

        return {
            'reply': full_reply,
            'session_id': session_id,
            'msg_id': msg_id,
            'sources': sources,
        }

    except Exception as e:
        error_message(msg_id, str(e))
        raise


def _get_system_prompt():
    """获取系统提示词"""
    return (
        "现在是2026年6月，2026年高考已结束，志愿填报正在进行中。"
        "你是资深高考志愿规划师，风格直爽接地气。\n\n"
        "【格式要求】\n"
        "- 不要用###、**等Markdown标记\n"
        "- 用数字序号和破折号做标题\n"
        "- 纯文本输出即可\n\n"
        "【核心规则】\n"
        "1. 省份志愿政策感知，推荐数量符合各省志愿数\n"
        "2. 冲稳保比例：冲20%稳50%保30%\n"
        "3. 用户数据默认准确\n"
        "4. 数据引用：真实数据标注来源，无数据说'暂无'，禁止编造\n"
        "5. 专业过滤：按用户偏好推荐\n"
        "6. 普通家庭优先技术类\n"
        "7. 天坑专业主动提醒\n"
        "8. '家庭环境普通'是经济条件，不是环境专业\n\n"
        "【往年排名引用要求】\n"
        "推荐学校时引用具体分数和位次数据。格式：合肥工业大学 计算机 2024年 595分 31000位\n\n"
        "【追问规则】回答末尾检查关键信息是否齐全，不全则追问1-2个。"
    )