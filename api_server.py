"""
iFixForU Dashboard API Server
从 Clover POS 拉取 8 家店实时数据，提供 JSON API 给看板前端。

启动: python3 api_server.py
端口: 8889
"""

import asyncio
import json
import logging
import sys
import os
from collections import defaultdict
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock

from db import get_today_items, get_active_notices, init_db

# 添加 CloverWatch 项目到路径
sys.path.insert(0, "/Users/Apple/PhpstormProjects/CloverWatch")
from config import STORES, CATEGORY_GROUPS, CLOVER_API_BASE, STORE_TIMEZONE
from clover_api import (
    fetch_orders,
    fetch_payments,
    compute_store_stats,
    day_range_ms,
    month_start_ms,
    get_tz,
    format_currency,
)

if sys.version_info >= (3, 9):
    from zoneinfo import ZoneInfo
else:
    from backports.zoneinfo import ZoneInfo

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 门店配置映射 ─────────────────────────────────────────────
STORE_DISPLAY = {
    "MPK1": {"code": "monterey_park", "display_name_en": "Monterey Park", "phone": "626-598-1888"},
    "Arcadia 1st": {"code": "arcadia_1", "display_name_en": "Arcadia 1", "phone": "626-600-8090"},
    "Arcadia 3rd": {"code": "arcadia_2", "display_name_en": "Arcadia 2", "phone": "626-777-9188"},
    "Rancho Cucamonga": {"code": "rancho_cucamonga", "display_name_en": "Rancho Cucamonga", "phone": "909-345-1000"},
    "San Gabriel": {"code": "san_gabriel", "display_name_en": "San Gabriel", "phone": "626-800-2030"},
    "Las Vegas 2nd": {"code": "las_vegas", "display_name_en": "Las Vegas", "phone": "702-779-8888"},
    "Rowland Heights": {"code": "rowland_heights", "display_name_en": "Rowland Heights", "phone": "909-789-0999"},
    "Irvine": {"code": "irvine", "display_name_en": "Irvine", "phone": "949-550-8000"},
}

# 分类映射到看板的 4 个品类
CATEGORY_TO_DASHBOARD = {
    "手机维修": "repair",
    "配件销售": "accessory",
    "运营商业务": "activation",
    "服务费": "repair",  # 服务费归入维修
    "其他": "sales",
}

# ── 缓存 ─────────────────────────────────────────────────────
cache_lock = Lock()
cached_data = None
cached_time = None
CACHE_TTL = 60  # 秒（每1分钟抓取一次）


# ── 数据抓取 ─────────────────────────────────────────────────

async def fetch_store_data(store: dict, start_ms: int, end_ms: int, client: httpx.AsyncClient) -> dict:
    """获取单店今日数据"""
    mid = store["merchant_id"]
    name = store["name"]
    display = STORE_DISPLAY.get(name, {"code": name.lower().replace(" ", "_"), "display_name_en": name})

    try:
        orders, payments = await asyncio.gather(
            fetch_orders(mid, start_ms, end_ms, client),
            fetch_payments(mid, start_ms, end_ms, client),
        )
        stats = compute_store_stats(orders, payments)

        # 员工业绩
        employee_stats = defaultdict(lambda: {"revenue": 0, "orders": 0})
        for order in orders:
            emp = order.get("employee", {})
            emp_name = emp.get("name", "Unknown")
            if not emp_name or emp_name == "Unknown":
                # 尝试从 line items 获取
                emp_name = "Staff"
            employee_stats[emp_name]["revenue"] += order.get("total", 0)
            employee_stats[emp_name]["orders"] += 1

        # 品类映射
        rev_breakdown = {"repair": 0, "activation": 0, "accessory": 0, "sales": 0}
        for cat_name, amount in stats["category_totals"].items():
            dash_key = CATEGORY_TO_DASHBOARD.get(cat_name, "sales")
            rev_breakdown[dash_key] += amount

        return {
            "store_name": name,
            "code": display["code"],
            "display_name_en": display["display_name_en"],
            "daily_revenue": stats["total_revenue"],
            "daily_orders": stats["order_count"],
            "avg_order": stats["avg_order"],
            "revenue_breakdown": rev_breakdown,
            "refund_total": stats["refund_total"],
            "refund_count": stats["refund_count"],
            "discount_total": stats["discount_total"],
            "credit_total": stats["credit_total"],
            "cash_total": stats["cash_total"],
            "employee_stats": dict(employee_stats),
            "error": None,
        }
    except Exception as e:
        logger.error("获取 %s 数据失败: %s", name, e)
        return {
            "store_name": name,
            "code": display["code"],
            "display_name_en": display["display_name_en"],
            "daily_revenue": 0,
            "daily_orders": 0,
            "avg_order": 0,
            "revenue_breakdown": {"repair": 0, "activation": 0, "accessory": 0, "sales": 0},
            "employee_stats": {},
            "error": str(e),
        }


async def fetch_monthly_revenue(store: dict, month_start: int, end_ms: int, client: httpx.AsyncClient) -> int:
    """获取单店本月累计营收"""
    mid = store["merchant_id"]
    try:
        orders = await fetch_orders(mid, month_start, end_ms, client)
        return sum(o.get("total", 0) for o in orders)
    except Exception as e:
        logger.error("获取 %s 月度数据失败: %s", store["name"], e)
        return 0


async def fetch_all_data(store_code: str = "san_gabriel") -> dict:
    """获取所有门店数据并汇总"""
    tz = get_tz()
    now = datetime.now(tz)
    day_start, day_end = day_range_ms(now)
    m_start = month_start_ms(now)

    async with httpx.AsyncClient() as client:
        # 并发获取所有门店今日数据
        daily_tasks = [fetch_store_data(s, day_start, day_end, client) for s in STORES]
        daily_results = await asyncio.gather(*daily_tasks)

        # 并发获取所有门店月度营收
        monthly_tasks = [fetch_monthly_revenue(s, m_start, day_end, client) for s in STORES]
        monthly_results = await asyncio.gather(*monthly_tasks)

    # 找到当前门店
    current_store = None
    for r in daily_results:
        if r["code"] == store_code:
            current_store = r
            break
    if not current_store:
        current_store = daily_results[0] if daily_results else {}

    # 构建排行榜（按日营收排序）
    rankings = []
    for i, r in enumerate(daily_results):
        rankings.append({
            "code": r["code"],
            "display_name_en": r["display_name_en"],
            "daily_revenue": r["daily_revenue"] / 100,  # cents -> dollars
            "daily_orders": r["daily_orders"],
        })
    rankings.sort(key=lambda x: x["daily_revenue"], reverse=True)

    # 月冠军
    month_data = []
    for i, r in enumerate(daily_results):
        month_data.append({
            "display_name_en": r["display_name_en"],
            "total": monthly_results[i] / 100,
        })
    month_data.sort(key=lambda x: x["total"], reverse=True)
    champion = month_data[0] if month_data else {"display_name_en": "-", "total": 0}

    # 当前门店的品类明细（cents -> dollars）
    cs = current_store
    breakdown = cs.get("revenue_breakdown", {})
    monthly_idx = next((i for i, s in enumerate(STORES) if STORE_DISPLAY.get(s["name"], {}).get("code") == store_code), 0)
    current_monthly = monthly_results[monthly_idx] / 100 if monthly_idx < len(monthly_results) else 0

    # 员工业绩（当前门店）
    emp_stats = cs.get("employee_stats", {})
    employee_rankings = []
    for name, data in emp_stats.items():
        employee_rankings.append({
            "name": name,
            "revenue": data["revenue"] / 100,
            "orders": data["orders"],
        })
    employee_rankings.sort(key=lambda x: x["revenue"], reverse=True)

    # 看板 items 和 notices（从 SQLite）
    try:
        items = get_today_items(store_code)
    except Exception as e:
        logger.error("获取 board items 失败: %s", e)
        items = []
    try:
        notices = get_active_notices(store_code)
    except Exception as e:
        logger.error("获取 notices 失败: %s", e)
        notices = []

    return {
        "store": {
            "code": store_code,
            "display_name_en": cs.get("display_name_en", ""),
            "monthly_target": 65000,
        },
        "sales": {
            "daily_revenue": cs.get("daily_revenue", 0) / 100,
            "daily_orders": cs.get("daily_orders", 0),
            "monthly_revenue": current_monthly,
        },
        "revenue_breakdown": {
            "repair": breakdown.get("repair", 0) / 100,
            "activation": breakdown.get("activation", 0) / 100,
            "accessory": breakdown.get("accessory", 0) / 100,
            "sales": breakdown.get("sales", 0) / 100,
        },
        "rankings": rankings,
        "month_champion": champion,
        "employee_rankings": employee_rankings,
        "store_count": len(STORES),
        "items": items,
        "notices": notices,
        "updated_at": now.isoformat(),
    }


def get_data_sync(store_code: str = "san_gabriel") -> dict:
    """同步封装异步抓取"""
    global cached_data, cached_time

    with cache_lock:
        if cached_data and cached_time and (datetime.now().timestamp() - cached_time) < CACHE_TTL:
            return cached_data

    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(fetch_all_data(store_code))
    finally:
        loop.close()

    with cache_lock:
        cached_data = data
        cached_time = datetime.now().timestamp()

    return data


# ── HTTP Server ──────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/dashboard"):
            # 解析 store_code 参数
            store_code = "san_gabriel"
            if "?" in self.path:
                params = self.path.split("?")[1]
                for p in params.split("&"):
                    if p.startswith("store="):
                        store_code = p.split("=")[1]

            try:
                data = get_data_sync(store_code)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            except Exception as e:
                logger.error("API error: %s", e)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        logger.info("%s %s", self.address_string(), format % args)


if __name__ == "__main__":
    port = 8889
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    logger.info("Dashboard API server running on http://localhost:%d", port)
    logger.info("Endpoint: http://localhost:%d/api/dashboard?store=san_gabriel", port)
    logger.info("Configured stores: %d", len(STORES))
    for s in STORES:
        logger.info("  - %s (%s)", s["name"], s["merchant_id"][:8] + "...")
    server.serve_forever()
