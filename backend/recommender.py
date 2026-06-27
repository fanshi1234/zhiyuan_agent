#!/usr/bin/env python3
"""志愿Agent — 冲稳保三档推荐引擎"""
import sqlite3

from .config import DATABASE_FILE
from .database import DB_AVAILABLE, _db_schema_version, get_custom_records


def build_recommendation(province, target_pos, target_score,
                         keywords=None, subject=None, school_filter=None):
    """生成冲稳保三档推荐

    优先使用自定义 Excel 数据，否则查询 SQLite 数据库。
    """
    if not province:
        return None

    # ---- 优先使用自定义数据 ----
    custom_data = get_custom_records()
    matched_custom = [
        r for r in custom_data
        if r.get("province", "") in province and r.get("score")
    ]
    if matched_custom:
        return _build_custom_recs(matched_custom, target_pos, target_score)

    if not (target_pos > 0 or target_score > 0):
        return None
    if not DB_AVAILABLE:
        return None

    conn = sqlite3.connect(str(DATABASE_FILE))
    is_v2 = _db_schema_version(conn)

    if is_v2:
        tier_a, tier_b, tier_c = _recommend_v2(
            conn, province, target_pos, target_score, keywords, subject,
        )
    else:
        tier_a, tier_b, tier_c = _recommend_v1(
            conn, province, target_pos, target_score, keywords,
        )
    conn.close()
    return {
        "pos": target_pos, "score": target_score,
        "chong": tier_a, "wen": tier_b, "bao": tier_c,
    }


def _build_custom_recs(custom_data, target_pos, target_score):
    """基于自定义 Excel 数据构建推荐（按分数排序分三档）"""
    grouped = {}
    for rec in custom_data:
        key = rec["school"] + "|" + rec.get("program", "")
        if key not in grouped:
            grouped[key] = {
                "school": rec["school"], "program": rec.get("program", ""),
                "scores": [], "positions": [], "years": [],
            }
        grouped[key]["scores"].append(rec["score"])
        grouped[key]["positions"].append(rec["position"])
        grouped[key]["years"].append(rec["year"])

    merged = []
    for key, grp in grouped.items():
        avg_sc = int(sum(grp["scores"]) / len(grp["scores"]))
        avg_po = int(sum(grp["positions"]) / len(grp["positions"]))
        prog_str = grp["program"]
        if len(grp["positions"]) >= 2:
            y0, y1 = grp["years"][0], grp["years"][1]
            s0, s1 = grp["scores"][0], grp["scores"][1]
            p0, p1 = grp["positions"][0], grp["positions"][1]
            if y0 == 2024:
                prog_str += f" [24:{s0}分/{p0}位 25:{s1}分/{p1}位]"
            else:
                prog_str += f" [24:{s1}分/{p1}位 25:{s0}分/{p0}位]"
        elif len(grp["positions"]) == 1:
            prog_str += f" [{grp['years'][0]}:{grp['scores'][0]}分/{grp['positions'][0]}位]"
        merged.append({
            "school": grp["school"], "program": prog_str,
            "score": avg_sc, "position": avg_po, "year": "综合",
        })

    n = len(merged)
    if n < 3:
        return {
            "pos": target_pos, "score": target_score,
            "chong": merged, "wen": [], "bao": [],
        }
    merged.sort(key=lambda x: x["position"])
    return {
        "pos": target_pos, "score": target_score,
        "chong": merged[:n // 3],
        "wen": merged[n // 3:2 * n // 3],
        "bao": merged[2 * n // 3:],
    }


def _to_records(conn, sql, params):
    return [
        {"school": r[0], "program": r[1], "score": r[2],
         "position": r[3], "year": r[4], "subject": r[5]}
        for r in conn.execute(sql, params).fetchall()
    ]


def _to_records_v1(conn, sql, params):
    return [
        {"school": r[0], "program": r[1], "score": r[2],
         "position": r[3], "year": r[4]}
        for r in conn.execute(sql, params).fetchall()
    ]


def _recommend_v2(conn, province, target_pos, target_score, keywords, subject):
    """v2 schema (major_scores 表) 推荐"""
    tier_a, tier_b, tier_c = [], [], []
    base = "province = ? AND (min_score>0 OR min_rank>0)"
    bp = [province]
    if subject:
        base += " AND subject LIKE ?"
        bp.append(f"%{subject}%")

    kw_part = ""
    if keywords:
        parts = []
        for kw in keywords.split(","):
            parts.append("(major LIKE ? OR major_group LIKE ? OR school LIKE ?)")
            bp += [f"%{kw}%", f"%{kw}%", f"%{kw}%"]
        kw_part = " AND (" + " OR ".join(parts) + ")"

    if target_pos > 0:
        where = base + kw_part + " AND batch NOT LIKE '%专科%' AND min_rank>0"
        tier_a = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {where} AND min_rank<? AND min_rank>=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp + [target_pos, max(1, int(target_pos * 0.90))],
        )
        tier_b = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {where} AND min_rank>=? AND min_rank<=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp + [target_pos, int(target_pos * 1.3)],
        )
        tier_c = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {where} AND min_rank>? AND min_rank<=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp + [int(target_pos * 1.3), int(target_pos * 1.6)],
        )

    # 渐进式回退：放宽关键词
    if not (tier_a or tier_b or tier_c) and keywords and target_pos > 0:
        bp2 = [province]
        if subject:
            bp2.append(f"%{subject}%")
        base2 = "province = ? AND batch NOT LIKE '%专科%' AND min_rank>0"
        if subject:
            base2 += " AND subject LIKE ?"
        tier_a = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {base2} AND min_rank<? AND min_rank>=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp2 + [target_pos, max(1, int(target_pos * 0.90))],
        )
        tier_b = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {base2} AND min_rank>=? AND min_rank<=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp2 + [target_pos, int(target_pos * 1.3)],
        )
        tier_c = _to_records(conn,
            f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
            f"WHERE {base2} AND min_rank>? AND min_rank<=? "
            f"ORDER BY min_rank ASC LIMIT 50",
            bp2 + [int(target_pos * 1.3), int(target_pos * 1.6)],
        )

    # 渐进式回退：继续放宽位次范围
    if not (tier_a or tier_b or tier_c) and target_pos > 0:
        for factor in [1.5, 2.0, 3.0]:
            if tier_a or tier_b or tier_c:
                break
            bp3 = [province]
            base3 = "province = ? AND min_rank>0"
            if subject:
                base3 += " AND subject LIKE ?"
                bp3.append(f"%{subject}%")
            tier_a = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_rank<? ORDER BY min_rank ASC LIMIT 50",
                bp3 + [max(1, int(target_pos * min(0.9, 1 / factor)))],
            )
            tier_b = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_rank>=? AND min_rank<=? "
                f"ORDER BY min_rank ASC LIMIT 50",
                bp3 + [target_pos, int(target_pos * factor)],
            )
            tier_c = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_rank>? AND min_rank<=? "
                f"ORDER BY min_rank ASC LIMIT 50",
                bp3 + [int(target_pos * factor), int(target_pos * factor * 1.5)],
            )

    # 最后尝试按分数
    if not (tier_a or tier_b or tier_c) and target_score > 0:
        bp3 = [province]
        base3 = "province = ?"
        if subject:
            base3 += " AND subject LIKE ?"
            bp3.append(f"%{subject}%")
        for window in [50, 100, 150]:
            if tier_a or tier_b or tier_c:
                break
            tier_a = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_score>? AND min_score<=? "
                f"ORDER BY min_score DESC LIMIT 80",
                bp3 + [target_score, target_score + window],
            )
            tier_b = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_score>=? AND min_score<=? "
                f"ORDER BY min_score ASC LIMIT 50",
                bp3 + [target_score - window, target_score + window],
            )
            tier_c = _to_records(conn,
                f"SELECT school,major,min_score,min_rank,year,subject FROM major_scores "
                f"WHERE {base3} AND min_score>=? AND min_score<? "
                f"ORDER BY min_score ASC LIMIT 50",
                bp3 + [target_score - window * 2, target_score - window],
            )
    return tier_a, tier_b, tier_c


def _recommend_v1(conn, province, target_pos, target_score, keywords):
    """v1 schema (admission 表) 推荐"""
    tier_a, tier_b, tier_c = [], [], []
    base = "province LIKE ? AND (score>0 OR rank>0)"
    bp = [f"%{province}%"]
    kw_part = ""
    if keywords:
        parts = []
        for kw in keywords.split(","):
            parts.append("(major_name LIKE ? OR school_name LIKE ?)")
            bp += [f"%{kw}%", f"%{kw}%"]
        kw_part = " AND (" + " OR ".join(parts) + ")"

    if target_pos > 0:
        where = base + kw_part
        tier_a = _to_records_v1(conn,
            f"SELECT school_name,major_name,score,rank,year FROM admission "
            f"WHERE {where} AND rank>0 AND rank<? AND rank>=? "
            f"ORDER BY rank ASC LIMIT 50",
            bp + [target_pos, max(1, int(target_pos * 0.90))],
        )
        tier_b = _to_records_v1(conn,
            f"SELECT school_name,major_name,score,rank,year FROM admission "
            f"WHERE {where} AND rank>0 AND rank>=? AND rank<=? "
            f"ORDER BY rank ASC LIMIT 50",
            bp + [target_pos, int(target_pos * 1.3)],
        )
        tier_c = _to_records_v1(conn,
            f"SELECT school_name,major_name,score,rank,year FROM admission "
            f"WHERE {where} AND rank>0 AND rank>? AND rank<=? "
            f"ORDER BY rank ASC LIMIT 50",
            bp + [int(target_pos * 1.3), int(target_pos * 1.6)],
        )
    return tier_a, tier_b, tier_c