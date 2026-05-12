"""
Dashboard Board Items & Notices — SQLite 数据层
数据库: dashboard.db（同目录下）
"""

from __future__ import annotations

import sqlite3
import os
from datetime import datetime, date
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """建表（幂等）"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS board_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_code TEXT NOT NULL DEFAULT 'san_gabriel',
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            display_emoji TEXT DEFAULT '📌',
            due_date TEXT,
            due_time TEXT,
            status TEXT DEFAULT 'pending',
            urgent INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'normal',
            creator_name TEXT,
            done_by TEXT,
            meta_ticket TEXT,
            meta_phone TEXT,
            meta_amount REAL,
            meta_paid INTEGER DEFAULT 0,
            meta_source TEXT,
            telegram_msg_id INTEGER,
            telegram_chat_id TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_code TEXT NOT NULL DEFAULT 'san_gabriel',
            content TEXT NOT NULL,
            display_emoji TEXT DEFAULT '📢',
            priority INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            creator_name TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            expires_at TEXT
        );
    """)
    conn.close()


def add_item(store_code: str, item: dict) -> int:
    """插入 board item，返回 id"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO board_items
           (store_code, type, content, display_emoji, due_date, due_time,
            status, urgent, priority, creator_name,
            meta_ticket, meta_phone, meta_amount, meta_paid, meta_source,
            telegram_msg_id, telegram_chat_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            store_code,
            item.get("type", "todo"),
            item.get("content", ""),
            item.get("display_emoji", "📌"),
            item.get("due_date"),
            item.get("due_time"),
            item.get("status", "pending"),
            1 if item.get("urgent") else 0,
            "urgent" if item.get("urgent") else "normal",
            item.get("creator_name"),
            item.get("meta", {}).get("ticket"),
            item.get("meta", {}).get("phone"),
            item.get("meta", {}).get("amount"),
            1 if item.get("meta", {}).get("paid") else 0,
            item.get("meta", {}).get("source"),
            item.get("telegram_msg_id"),
            item.get("telegram_chat_id"),
        ),
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def add_notice(store_code: str, notice: dict) -> int:
    """插入 notice，返回 id"""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO notices
           (store_code, content, display_emoji, priority, creator_name, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            store_code,
            notice.get("content", ""),
            notice.get("display_emoji", "📢"),
            notice.get("priority", 1),
            notice.get("creator_name"),
            notice.get("expires_at"),
        ),
    )
    notice_id = cur.lastrowid
    conn.commit()
    conn.close()
    return notice_id


def get_today_items(store_code: str) -> list:
    """获取所有 pending 的 board items（未完成的持续显示，不限创建日期）"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM board_items
           WHERE store_code = ?
             AND status = 'pending'
             AND type != 'wechat_report'
           ORDER BY urgent DESC, created_at DESC""",
        (store_code,),
    ).fetchall()
    conn.close()
    return [item_to_api_format(r) for r in rows]


def get_active_notices(store_code: str) -> list:
    """获取有效公告（未过期、active=1）"""
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT * FROM notices
           WHERE store_code = ?
             AND active = 1
             AND (expires_at IS NULL OR expires_at > ?)
           ORDER BY priority DESC, created_at DESC""",
        (store_code, now),
    ).fetchall()
    conn.close()
    return [notice_to_api_format(r) for r in rows]


def mark_done(item_id: int, done_by: str = None) -> bool:
    """标记 board item 为已完成"""
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """UPDATE board_items SET status = 'done', done_by = ?, updated_at = ?
           WHERE id = ? AND status = 'pending'""",
        (done_by, now, item_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_item(item_id: int) -> bool:
    """删除 board item"""
    conn = get_conn()
    cur = conn.execute("DELETE FROM board_items WHERE id = ?", (item_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def get_item(item_id: int) -> Optional[dict]:
    """获取单条 item"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM board_items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Admin 查询 ────────────────────────────────────────────────

def get_items_history(store_code: str, days: int = 7, item_type: str = None, status: str = None) -> list:
    """获取最近 N 天的 board items（Admin 用，不限 today）"""
    conn = get_conn()
    sql = "SELECT * FROM board_items WHERE store_code = ? AND created_at >= datetime('now', 'localtime', ?)"
    params = [store_code, f"-{days} days"]
    if item_type:
        sql += " AND type = ?"
        params.append(item_type)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [item_to_admin_format(r) for r in rows]


def get_all_notices_admin(store_code: str) -> list:
    """获取所有公告（Admin 用，含过期和非活跃）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notices WHERE store_code = ? ORDER BY created_at DESC",
        (store_code,),
    ).fetchall()
    conn.close()
    return [notice_to_admin_format(r) for r in rows]


def get_admin_stats(store_code: str) -> dict:
    """Admin 统计摘要"""
    conn = get_conn()
    today = date.today().isoformat()
    today_total = conn.execute(
        "SELECT COUNT(*) FROM board_items WHERE store_code = ? AND date(created_at) = ?",
        (store_code, today),
    ).fetchone()[0]
    today_done = conn.execute(
        "SELECT COUNT(*) FROM board_items WHERE store_code = ? AND date(created_at) = ? AND status = 'done'",
        (store_code, today),
    ).fetchone()[0]
    week_total = conn.execute(
        "SELECT COUNT(*) FROM board_items WHERE store_code = ? AND created_at >= datetime('now', 'localtime', '-7 days')",
        (store_code,),
    ).fetchone()[0]
    active_notices = conn.execute(
        "SELECT COUNT(*) FROM notices WHERE store_code = ? AND active = 1",
        (store_code,),
    ).fetchone()[0]
    by_type = {}
    for row in conn.execute(
        "SELECT type, COUNT(*) as cnt FROM board_items WHERE store_code = ? AND date(created_at) = ? GROUP BY type",
        (store_code, today),
    ).fetchall():
        by_type[row[0]] = row[1]
    conn.close()
    return {
        "today_total": today_total,
        "today_done": today_done,
        "today_pending": today_total - today_done,
        "week_total": week_total,
        "active_notices": active_notices,
        "by_type": by_type,
    }


def deactivate_notice(notice_id: int) -> bool:
    """停用公告"""
    conn = get_conn()
    cur = conn.execute("UPDATE notices SET active = 0 WHERE id = ?", (notice_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def item_to_admin_format(row) -> dict:
    """Admin 格式：包含所有字段"""
    r = dict(row)
    return {
        "id": r["id"],
        "type": r["type"],
        "label": TYPE_LABELS.get(r["type"], r["type"]),
        "content": r["content"],
        "display_emoji": r["display_emoji"],
        "status": r["status"],
        "urgent": bool(r.get("urgent")),
        "creator_name": r.get("creator_name", ""),
        "done_by": r.get("done_by", ""),
        "created_at": r.get("created_at", ""),
        "updated_at": r.get("updated_at", ""),
        "due_date": r.get("due_date", ""),
        "due_time": r.get("due_time", ""),
        "meta": {
            "ticket": r.get("meta_ticket"),
            "phone": r.get("meta_phone"),
            "amount": r.get("meta_amount"),
            "paid": bool(r.get("meta_paid")),
            "source": r.get("meta_source"),
        },
    }


def notice_to_admin_format(row) -> dict:
    r = dict(row)
    return {
        "id": r["id"],
        "content": r["content"],
        "display_emoji": r.get("display_emoji", "📢"),
        "priority": r.get("priority", 1),
        "active": bool(r.get("active", 1)),
        "creator_name": r.get("creator_name", ""),
        "created_at": r.get("created_at", ""),
        "expires_at": r.get("expires_at"),
    }


# ── 格式转换 ─────────────────────────────────────────────────

TYPE_LABELS = {
    "customer_followup": "客户跟进",
    "incoming_inventory": "到货提醒",
    "handoff": "交班事项",
    "repair_pending": "维修等待",
    "todo": "待办",
    "wechat_report": "微信报备",
}


def item_to_api_format(row) -> dict:
    """行数据转 API 格式，匹配前端 MOCK_DATA.items 结构"""
    r = dict(row)
    meta = {}
    if r.get("meta_ticket"):
        meta["ticket"] = r["meta_ticket"]
    if r.get("meta_phone"):
        meta["phone"] = r["meta_phone"]
    if r.get("meta_amount") is not None:
        meta["amount"] = r["meta_amount"]
        meta["paid"] = bool(r.get("meta_paid"))
    if r.get("meta_source"):
        meta["source"] = r["meta_source"]

    result = {
        "id": r["id"],
        "type": r["type"],
        "label": TYPE_LABELS.get(r["type"], r["type"]),
        "content": r["content"],
        "display_emoji": r["display_emoji"],
        "status": r["status"],
        "urgent": bool(r.get("urgent")),
        "creator_name": r.get("creator_name", ""),
        "created_at": r.get("created_at", ""),
    }
    if r.get("due_time"):
        result["due_time"] = r["due_time"]
    if r.get("due_date"):
        result["due_date"] = r["due_date"]
    if meta:
        result["meta"] = meta
    return result


def notice_to_api_format(row) -> dict:
    """notice 行数据转 API 格式"""
    r = dict(row)
    return {
        "id": r["id"],
        "content": r["content"],
        "emoji": r.get("display_emoji", "📢"),
        "priority": r.get("priority", 1),
        "creator": r.get("creator_name", ""),
        "created_at": r.get("created_at", ""),
    }


# ── 微信好友统计 ───────────────────────────────────────────────

WECHAT_BASELINES = {
    "san_gabriel": 6150,
    "arcadia_1": 94,
    "las_vegas": 2847,
}


def _get_baseline(store_code: str) -> int:
    return WECHAT_BASELINES.get(store_code, 0)


def get_wechat_total(store_code: str) -> dict:
    """获取微信好友累计总数和今日新增"""
    conn = get_conn()
    today = date.today().isoformat()
    today_added = conn.execute(
        "SELECT COALESCE(SUM(meta_amount), 0) FROM board_items "
        "WHERE store_code = ? AND type = 'wechat_report' AND date(created_at) = ?",
        (store_code, today)).fetchone()[0]
    all_added = conn.execute(
        "SELECT COALESCE(SUM(meta_amount), 0) FROM board_items "
        "WHERE store_code = ? AND type = 'wechat_report'",
        (store_code,)).fetchone()[0]
    conn.close()
    return {"today_added": int(today_added), "total": _get_baseline(store_code) + int(all_added)}


# 启动时自动建表
init_db()
