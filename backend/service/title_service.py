#!/usr/bin/env python3
"""志愿Agent — 会话标题生成服务"""
import re

GREETINGS = {
    '你好', '您好', '嗨', 'hi', 'hello', '在吗', '有人在吗',
    '你好啊', '你好呀', '在不在', '帮忙', '帮帮忙', '帮我看下',
    '帮我看一下', '帮我看看', '我想咨询', '我想咨询一下', '咨询一下',
    '请问', '请教', '老师好', '老师你好', '大师好', '顾问好',
}

PROVS = [
    '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
    '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
    '广东', '广西', '海南', '四川', '贵州', '云南', '西藏', '陕西', '甘肃',
    '青海', '宁夏', '新疆', '内蒙古',
]

SUBJECT_ABBR = {
    ('物理', '化学', '生物'): '物化生',
    ('物理', '化学', '政治'): '物化政',
    ('物理', '化学', '地理'): '物化地',
    ('物理', '化学', '历史'): '物化史',
    ('物理', '生物', '政治'): '物生政',
    ('物理', '生物', '地理'): '物生地',
    ('物理', '政治', '地理'): '物政地',
    ('历史', '政治', '地理'): '史政地',
    ('历史', '地理', '生物'): '史地生',
    ('历史', '政治', '生物'): '史政生',
    ('历史', '化学', '生物'): '史化生',
}

SUBJECT_SIMPLE = {
    '物理类': '物', '历史类': '史', '理科': '理', '文科': '文',
    '物理': '物', '历史': '史', '理科': '理', '文科': '文',
}

REGION_NEAR_HOME = {
    '离家近', '省内', '本省', '本地', '就近', '离家近一点', '离家近一些',
    '长三角', '珠三角', '京津冀', '中部', '华东', '华南', '华北', '西南',
}

DEMAND_KEYWORDS = {
    '冲211', '冲985', '保公办', '考公', '考公务员', '考研', '就业',
    '稳定', '公办', '行业强校', '军校', '警校', '师范',
}


def is_greeting(text):
    """判断是否为寒暄类消息"""
    cleaned = text.strip().rstrip('！!。.,，,,。。;;：:～~')
    if len(cleaned) > 8:
        return False
    for g in GREETINGS:
        if cleaned == g or cleaned.startswith(g + '，') or cleaned.startswith(g + ',') or cleaned.startswith(g + ' '):
            return True
    return False


def subjects_to_short(subject):
    """将选科转换为简称
    支持: 字符串 "物化生", "物理类", 或 JSON 数组
    """
    if not subject:
        return ''
    # 已经是简称 (物化生, 物化政, 史政地 等)
    if re.match(r'^[物史理化政地生]{2,4}$', subject):
        return subject
    # 科目类别 (物理类, 历史类, 文科, 理科)
    simple = SUBJECT_SIMPLE.get(subject, '')
    if simple:
        return simple
    # 尝试解析为 JSON 数组
    try:
        import json
        subjects = json.loads(subject)
        if isinstance(subjects, list) and len(subjects) >= 2:
            key = tuple(sorted(subjects))
            short = SUBJECT_ABBR.get(key)
            if short:
                return short
            # 回退: 取每个科目首字
            return ''.join(s[0] for s in subjects if s)
    except Exception:
        pass
    return subject[:4] if subject else ''


def extract_major_pref(profile):
    """从画像中提取专业偏好简称"""
    major_pref = profile.get('major_pref', '')
    if not major_pref:
        return ''
    try:
        if isinstance(major_pref, str):
            import json
            majors = json.loads(major_pref)
        else:
            majors = major_pref
        if isinstance(majors, list) and majors:
            return majors[0][:4]
    except Exception:
        pass
    return str(major_pref)[:4]


def extract_demand_type(profile, user_message):
    """从画像和消息中提取需求类型"""
    combined = (user_message or '') + (profile.get('career_goal') or '')
    for kw in DEMAND_KEYWORDS:
        if kw in combined:
            return kw
    # 默认需求类型
    if profile.get('major_pref'):
        return ''
    return '择校'


def extract_region_keyword(profile):
    """提取地域偏好关键词"""
    region_pref = profile.get('region_pref', '')
    if isinstance(region_pref, str):
        for kw in REGION_NEAR_HOME:
            if kw in region_pref:
                return kw[:4]
        try:
            import json
            regions = json.loads(region_pref)
            if isinstance(regions, list) and regions:
                return regions[0][:4]
        except Exception:
            pass
    return ''


def generate_conversation_title(user_message, profile):
    """生成会话标题

    Args:
        user_message: 用户当前消息
        profile: 考生画像字典 (可能为 None)

    Returns:
        简短标题字符串 (8-18 个中文字符)
    """
    # 寒暄检测
    if is_greeting(user_message):
        return '新对话'

    if not profile:
        return '新对话'

    province = profile.get('province', '')
    score = profile.get('score', 0) or 0
    rank = profile.get('rank', 0) or 0
    subject = subjects_to_short(profile.get('subject', ''))
    major = extract_major_pref(profile)
    demand = extract_demand_type(profile, user_message)
    region_kw = extract_region_keyword(profile)

    # 规则 1: 省份 + 选科 + 分数 + 需求
    if province and subject and score:
        if major:
            return f"{province}{subject}{score}分{major}"
        demand_suffix = demand if demand and demand != '择校' else '择校'
        return f"{province}{subject}{score}分{demand_suffix}"

    # 规则 2: 省份 + 位次 (无分数)
    if province and rank and not score:
        return f"{province}{rank}名冲稳保"

    # 规则 3: 省份 + 分数 (无选科)
    if province and score and not subject:
        return f"{province}{score}分志愿"

    # 规则 4: 省份 + 专业偏好
    if province and major:
        return f"{province}{major}专业推荐"

    # 规则 5: 省份 + 地域偏好
    if province and region_kw:
        return f"{province}{region_kw}择校"

    # 只有省份
    if province:
        return '新对话'

    return '新对话'


def try_auto_title(user_message, profile):
    """尝试生成自动标题，信息不足时返回 None"""
    if is_greeting(user_message):
        return None

    if not profile:
        return None

    # 至少需要省份 + (分数 或 位次) 才有意义
    has_province = bool(profile.get('province'))
    has_score = bool(profile.get('score'))
    has_rank = bool(profile.get('rank'))

    if not has_province or (not has_score and not has_rank):
        return None

    title = generate_conversation_title(user_message, profile)
    if title and title != '新对话':
        return title

    return None