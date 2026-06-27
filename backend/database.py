#!/usr/bin/env python3
"""志愿Agent — 数据库操作：初始化、查询"""
import gzip
import shutil
import sqlite3

from .config import DATABASE_FILE, DATABASE_GZ, KB_DATABASE_FILE, ROOT_DIR

DB_AVAILABLE = False


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
# 初始化
# ============================================================
DB_AVAILABLE = ensure_database()