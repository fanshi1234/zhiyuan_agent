#!/usr/bin/env python3
"""志愿Agent — 数据库操作：初始化、查询、自定义 Excel 数据加载"""
import gzip
import shutil
import sqlite3

from .config import DATABASE_FILE, DATABASE_GZ, KB_DATABASE_FILE, CUSTOM_EXCEL, ROOT_DIR

DB_AVAILABLE = False
_custom_records = []


# ============================================================
# 数据库初始化
# ============================================================

def ensure_database():
    """初始化数据库：优先从 KB 副本加载，其次 gzip，最后旧格式文件"""
    global DB_AVAILABLE
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if KB_DATABASE_FILE.exists():
        if not DATABASE_FILE.exists():
            shutil.copy2(KB_DATABASE_FILE, DATABASE_FILE)
        DB_AVAILABLE = True
        return True
    if DATABASE_FILE.exists():
        DB_AVAILABLE = True
        return True
    if DATABASE_GZ.exists():
        with gzip.open(DATABASE_GZ, "rb") as src, open(DATABASE_FILE, "wb") as dst:
            shutil.copyfileobj(src, dst)
        DB_AVAILABLE = DATABASE_FILE.exists()
        return DB_AVAILABLE
    # 兼容旧文件名
    old_db = ROOT_DIR / "admission_clean.db"
    old_gz = ROOT_DIR / "admission_clean.db.gz"
    if old_db.exists():
        shutil.copy2(old_db, DATABASE_FILE)
        DB_AVAILABLE = True
        return True
    if old_gz.exists():
        with gzip.open(old_gz, "rb") as src, open(DATABASE_FILE, "wb") as dst:
            shutil.copyfileobj(src, dst)
        DB_AVAILABLE = True
        return True
    return False


def _db_schema_version(conn):
    table_names = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    return "major_scores" in table_names


# ============================================================
# 通用查询
# ============================================================

def search_admissions(province=None, school_name=None, program_name=None, max_rows=50):
    """按省份/学校/专业查询录取数据"""
    if not DB_AVAILABLE:
        return None
    conn = sqlite3.connect(str(DATABASE_FILE))
    is_v2 = _db_schema_version(conn)
    clauses, params = [], []
    if province:
        if is_v2:
            clauses.append("province = ?")
        else:
            clauses.append("province LIKE ?")
        params.append(f"%{province}%" if not is_v2 else province)
    if school_name:
        field = "school" if is_v2 else "school_name"
        clauses.append(f"{field} LIKE ?")
        params.append(f"%{school_name}%")
    if program_name:
        field = "major" if is_v2 else "major_name"
        clauses.append(f"{field} LIKE ?")
        params.append(f"%{program_name}%")
    if not clauses:
        conn.close()
        return None
    where = " AND ".join(clauses)
    if is_v2:
        sql = (
            f"SELECT province,year,school,major,min_score,min_rank "
            f"FROM major_scores WHERE {where} AND min_rank>100 "
            f"ORDER BY year DESC,min_rank ASC LIMIT ?"
        )
    else:
        sql = (
            f"SELECT province,year,school_name,major_name,score,rank "
            f"FROM admission WHERE {where} AND rank>100 "
            f"ORDER BY year DESC,rank ASC LIMIT ?"
        )
    params.append(max_rows)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {"province": r[0], "year": r[1], "school": r[2], "program": r[3],
         "score": r[4], "position": r[5]}
        for r in rows
    ]


def province_stats(province):
    """获取某省份的数据统计"""
    if not DB_AVAILABLE or not province:
        return {
            "province": province, "total": 0, "min_pos": 0,
            "max_pos": 0, "schools": 0, "programs": 0,
        }
    conn = sqlite3.connect(str(DATABASE_FILE))
    is_v2 = _db_schema_version(conn)
    if is_v2:
        row = conn.execute(
            "SELECT COUNT(*), MIN(min_rank), MAX(min_rank), AVG(min_rank), "
            "COUNT(DISTINCT school), COUNT(DISTINCT major) "
            "FROM major_scores WHERE province = ? AND min_rank > 0",
            (province,),
        ).fetchone()
        conn.close()
        return {
            "province": province, "total": row[0],
            "min_pos": row[1] or 0, "max_pos": row[2] or 0,
            "avg_pos": int(row[3]) if row[3] else 0,
            "schools": row[4], "programs": row[5],
        }
    row = conn.execute(
        "SELECT COUNT(*), MIN(rank), MAX(rank), AVG(rank) "
        "FROM admission WHERE province LIKE ? AND rank > 0",
        (f"%{province}%",),
    ).fetchone()
    conn.close()
    return {
        "province": province, "total": row[0],
        "min_pos": row[1] or 0, "max_pos": row[2] or 0,
        "avg_pos": int(row[3]) if row[3] else 0,
        "schools": 0, "programs": 0,
    }


# ============================================================
# 自定义 Excel 数据
# ============================================================

def _parse_number(val):
    if val is None:
        return None
    text = str(val).strip().replace(",", "").replace("，", "").replace(" ", "")
    text = text.replace("分", "").replace("位", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def refresh_custom_data():
    """从 用户数据表.xlsx 加载自定义填报数据"""
    global _custom_records
    _custom_records = []
    if not CUSTOM_EXCEL.exists():
        return
    try:
        import openpyxl as xl
    except ImportError:
        print("[custom data] openpyxl 未安装，无法加载自定义数据")
        return
    try:
        book = xl.load_workbook(str(CUSTOM_EXCEL), data_only=True)
        sheet = book.active
        for row_cells in sheet.iter_rows(min_row=2, values_only=True):
            school_cell = row_cells[0] if len(row_cells) > 0 else None
            if school_cell is None:
                continue
            school_name = str(school_cell).strip()
            if len(school_name) < 2:
                continue
            if school_name in ("学校名称", "院校名称"):
                continue
            remark = str(row_cells[8]).strip() if len(row_cells) > 8 and row_cells[8] else ""
            if "示例" in remark or "不参与排序" in remark:
                continue
            major_name = str(row_cells[1]).strip() if len(row_cells) > 1 and row_cells[1] else ""
            category_raw = str(row_cells[2]).strip() if len(row_cells) > 2 and row_cells[2] else ""
            if "物理" in category_raw:
                cat = "物理类"
            elif "历史" in category_raw:
                cat = "历史类"
            elif "综合" in category_raw:
                cat = "综合"
            else:
                cat = category_raw
            prov_raw = str(row_cells[3]).strip().replace("省", "").replace("市", "").strip() \
                if len(row_cells) > 3 and row_cells[3] else ""
            s24 = _parse_number(row_cells[4]) if len(row_cells) > 4 else None
            r24 = _parse_number(row_cells[5]) if len(row_cells) > 5 else None
            s25 = _parse_number(row_cells[6]) if len(row_cells) > 6 else None
            r25 = _parse_number(row_cells[7]) if len(row_cells) > 7 else None
            # 交换分数和位次（如果搞反了）
            if s24 is not None and s24 < 100 and r24 is not None and r24 > 300:
                s24, r24 = r24, s24
            if s25 is not None and s25 < 100 and r25 is not None and r25 > 300:
                s25, r25 = r25, s25
            if s24 is not None and r24 is not None:
                _custom_records.append({
                    "school": school_name, "program": major_name, "year": 2024,
                    "category": cat, "score": s24, "position": r24, "province": prov_raw,
                })
            if s25 is not None and r25 is not None:
                _custom_records.append({
                    "school": school_name, "program": major_name, "year": 2025,
                    "category": cat, "score": s25, "position": r25, "province": prov_raw,
                })
        book.close()
        print(f"[custom data] 已加载 {len(_custom_records)} 条自定义数据")
    except Exception as exc:
        print(f"[custom data] 加载失败: {exc}")


def get_custom_records():
    return list(_custom_records)


def custom_data_count():
    return len(_custom_records)


# ============================================================
# 初始化
# ============================================================
DB_AVAILABLE = ensure_database()
refresh_custom_data()