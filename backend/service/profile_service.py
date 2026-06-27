#!/usr/bin/env python3
"""志愿Agent — 考生画像抽取和更新服务"""
import json
from ..repo.profile_repo import get, create_or_update
from ..llm_proxy import extract_user_info


def get_profile(conv_id):
    """获取会话对应的考生画像"""
    return get(conv_id)


def update_profile_from_message(conv_id, user_message):
    """从用户消息中抽取并更新画像
    返回新的画像数据
    """
    # 先用正则快速提取
    info = _regex_extract(user_message)

    # 尝试 LLM 提取（如果正则提取的信息不够）
    try:
        llm_info = extract_user_info(user_message)
        if llm_info:
            # LLM 结果优先级更高，但正则结果作为补充
            if not llm_info.get('province') and info.get('province'):
                llm_info['province'] = info['province']
            if not llm_info.get('rank') and info.get('rank'):
                llm_info['rank'] = info['rank']
            if not llm_info.get('score') and info.get('score'):
                llm_info['score'] = info['score']
            info = llm_info
    except Exception:
        pass  # LLM 提取失败，用正则结果

    if not info:
        return None

    # 映射到画像字段
    profile_fields = {
        'province': info.get('province', ''),
        'year': 2026,
        'score': int(info.get('score', 0) or 0),
        'rank': int(info.get('rank', 0) or 0),
        'subject': info.get('subject', ''),
        'family_condition': info.get('family_condition', ''),
        'region_pref': info.get('region_pref', []),
        'region_avoid': info.get('region_avoid', []),
        'major_pref': info.get('majors', []),
        'school_pref': info.get('schools', []),
        'career_goal': info.get('career_goal', ''),
    }

    # 过滤空值
    raw_json = json.dumps(info, ensure_ascii=False)
    profile_fields['raw_json'] = raw_json

    create_or_update(conv_id, **profile_fields)
    return get(conv_id)


def _regex_extract(text):
    """正则快速提取"""
    info = {}

    # 省份
    provs = ['北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
             '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
             '广东', '广西', '海南', '四川', '贵州', '云南', '西藏', '陕西', '甘肃',
             '青海', '宁夏', '新疆', '内蒙古']
    best = len(text)
    for p in provs:
        idx = text.find(p)
        if 0 <= idx < best:
            best = idx
            info['province'] = p

    # 位次
    import re
    rm = re.search(r'(\d{4,7})\s*[位名]', text) or re.search(r'[位名]次?\s*(\d{4,7})', text)
    if rm:
        info['rank'] = int(rm.group(1))

    # 分数
    sm = re.search(r'(\d{3})\s*分', text)
    if sm:
        info['score'] = int(sm.group(1))

    # 选科
    if '物理' in text or '物化' in text:
        info['subject'] = '物理类'
    elif '历史' in text or '文史' in text or '文科' in text:
        info['subject'] = '历史类'
    elif '理科' in text:
        info['subject'] = '理科'

    return info


def build_context_string(profile):
    """将画像转换为 LLM 上下文字符串"""
    if not profile:
        return ""
    lines = []
    if profile.get('province'):
        lines.append(f"考生省份: {profile['province']}")
    if profile.get('year'):
        lines.append(f"高考年份: {profile['year']}")
    if profile.get('score'):
        lines.append(f"分数: {profile['score']}")
    if profile.get('rank'):
        lines.append(f"全省位次: {profile['rank']}")
    if profile.get('subject'):
        lines.append(f"选科: {profile['subject']}")
    if profile.get('family_condition'):
        lines.append(f"家庭条件: {profile['family_condition']}")
    if profile.get('major_pref'):
        try:
            majors = json.loads(profile['major_pref']) if isinstance(profile['major_pref'], str) else profile['major_pref']
            if majors:
                lines.append(f"专业偏好: {', '.join(majors)}")
        except Exception:
            lines.append(f"专业偏好: {profile['major_pref']}")
    if profile.get('region_pref'):
        try:
            regions = json.loads(profile['region_pref']) if isinstance(profile['region_pref'], str) else profile['region_pref']
            if regions:
                lines.append(f"地域偏好: {', '.join(regions)}")
        except Exception:
            pass
    if profile.get('region_avoid'):
        try:
            avoids = json.loads(profile['region_avoid']) if isinstance(profile['region_avoid'], str) else profile['region_avoid']
            if avoids:
                lines.append(f"地域回避: {', '.join(avoids)}")
        except Exception:
            pass
    if profile.get('career_goal'):
        lines.append(f"职业目标: {profile['career_goal']}")
    return '\n'.join(lines)