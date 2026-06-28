#!/usr/bin/env python3
"""志愿Agent — candidate_profiles 表 CRUD"""
import time
from .db import get_conn


def get(conv_id):
    """获取会话对应的考生画像"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, conversation_id, province, year, score, rank, subject, "
        "family_condition, region_pref, region_avoid, major_pref, school_pref, "
        "risk_preference, budget_pref, career_goal, raw_json, created_at, updated_at "
        "FROM candidate_profiles WHERE conversation_id=?",
        (conv_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip([
        'id', 'conversation_id', 'province', 'year', 'score', 'rank', 'subject',
        'family_condition', 'region_pref', 'region_avoid', 'major_pref', 'school_pref',
        'risk_preference', 'budget_pref', 'career_goal', 'raw_json', 'created_at', 'updated_at'
    ], row))


def create_or_update(conv_id, **kwargs):
    """创建或更新画像"""
    conn = get_conn()
    now = time.time()

    # 检查是否已存在
    existing = conn.execute(
        "SELECT id FROM candidate_profiles WHERE conversation_id=?", (conv_id,)
    ).fetchone()

    fields = ['province', 'year', 'score', 'rank', 'subject',
              'family_condition', 'region_pref', 'region_avoid', 'major_pref',
              'school_pref', 'risk_preference', 'budget_pref', 'career_goal', 'raw_json']

    if existing:
        # 更新非空字段
        sets = []
        vals = []
        for f in fields:
            if f in kwargs and kwargs[f] is not None:
                sets.append(f"{f}=?")
                vals.append(_to_json(kwargs[f]) if f.endswith('_pref') or f == 'region_avoid' or f == 'raw_json' else kwargs[f])
        if sets:
            sets.append("updated_at=?")
            vals.extend([now, conv_id])
            conn.execute(
                f"UPDATE candidate_profiles SET {','.join(sets)} WHERE conversation_id=?",
                vals
            )
    else:
        # 新建
        values = []
        placeholders = []
        values.append(conv_id)
        placeholders.append("conversation_id")
        for f in fields:
            val = kwargs.get(f, '')
            if f.endswith('_pref') or f == 'region_avoid' or f == 'raw_json':
                val = _to_json(val) if val is not None and val != '' else ''
            values.append(val)
            placeholders.append(f)
        values.extend([now, now])
        placeholders.extend(['created_at', 'updated_at'])

        conn.execute(
            f"INSERT INTO candidate_profiles ({','.join(placeholders)}) VALUES ({','.join(['?']*len(placeholders))})",
            values
        )

    conn.commit()
    conn.close()


def _to_json(val):
    """序列化为 JSON 字符串"""
    if isinstance(val, str):
        return val
    try:
        return __import__('json').dumps(val, ensure_ascii=False)
    except Exception:
        return str(val)


def delete(conv_id):
    """删除画像"""
    conn = get_conn()
    conn.execute("DELETE FROM candidate_profiles WHERE conversation_id=?", (conv_id,))
    conn.commit()
    conn.close()