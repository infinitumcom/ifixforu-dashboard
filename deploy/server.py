"""
iFixForU Dashboard API Server (Standalone)
从 Clover POS 拉取 8 家店实时数据，提供 JSON API + 静态文件服务。

启动: /opt/dashboard-venv/bin/python /opt/dashboard/server.py
端口: 8889
"""

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import httpx

from db import get_wechat_total, init_db, get_today_items, get_active_notices

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 加载 .env ─────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── 门店配置 ─────────────────────────────────────────────────
CLOVER_API_BASE = "https://api.clover.com"
STORE_TIMEZONE = os.getenv("STORE_TIMEZONE", "America/Los_Angeles")

STORES = [
    {"name": "MPK1", "merchant_id": os.getenv("STORE_1_MID", ""), "api_token": os.getenv("STORE_1_TOKEN", "")},
    {"name": "Arcadia 1st", "merchant_id": os.getenv("STORE_2_MID", ""), "api_token": os.getenv("STORE_2_TOKEN", "")},
    {"name": "Arcadia 3rd", "merchant_id": os.getenv("STORE_3_MID", ""), "api_token": os.getenv("STORE_3_TOKEN", "")},
    {"name": "Rancho Cucamonga", "merchant_id": os.getenv("STORE_4_MID", ""), "api_token": os.getenv("STORE_4_TOKEN", "")},
    {"name": "San Gabriel", "merchant_id": os.getenv("STORE_5_MID", ""), "api_token": os.getenv("STORE_5_TOKEN", "")},
    {"name": "Las Vegas 2nd", "merchant_id": os.getenv("STORE_6_MID", ""), "api_token": os.getenv("STORE_6_TOKEN", "")},
    {"name": "Rowland Heights", "merchant_id": os.getenv("STORE_7_MID", ""), "api_token": os.getenv("STORE_7_TOKEN", "")},
    {"name": "Irvine", "merchant_id": os.getenv("STORE_8_MID", ""), "api_token": os.getenv("STORE_8_TOKEN", "")},
]

CATEGORY_GROUPS = [
    {"name": "手机维修", "keywords": ["screen repair", "battery replacement", "charging port", "other repair", "repair", "replacement", "screen", "battery", "camera", "button", "speaker", "housing", "antenna", "jack", "vibrator", "motherboard", "cleaning"]},
    {"name": "配件销售", "keywords": ["screen protector", "phone case", "other accessories", "protector", "accessories", "accessory", "case", "cable", "charger", "earphone", "security"]},
    {"name": "运营商业务", "keywords": ["cricket", "at&t", "t-mobile", "metro", "verizon", "simple mobile", "ct-mobile", "ultra", "h2o", "lyca", "surf mobile", "ecc", "activation", "recharge", "sim card", "other carriers"]},
    {"name": "服务费", "keywords": ["service fee", "diagnostic", "rush", "labor", "deposit", "transaction fee"]},
]

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

CATEGORY_TO_DASHBOARD = {
    "手机维修": "repair",
    "配件销售": "accessory",
    "运营商业务": "activation",
    "服务费": "repair",
    "其他": "sales",
}

# ── 工具函数 ─────────────────────────────────────────────────

def get_tz():
    return ZoneInfo(STORE_TIMEZONE)

def day_range_ms(dt):
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

def month_start_ms(dt):
    first = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(first.timestamp() * 1000)

def get_store_token(merchant_id):
    for store in STORES:
        if store["merchant_id"] == merchant_id:
            return store["api_token"]
    return ""

def classify_category(cat_name):
    lower = cat_name.lower()
    for group in CATEGORY_GROUPS:
        for keyword in group["keywords"]:
            if keyword in lower:
                return group["name"]
    return "其他"

# ── API 请求（含重试）───────────────────────────────────────

MAX_RETRIES = 3

async def _request_with_retry(client, url, headers, timeout=30):
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, headers=headers, timeout=timeout)
            if resp.status_code < 500:
                return resp
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                return resp
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                return None
    return None

async def fetch_orders(merchant_id, start_ms, end_ms, client):
    headers = {"Authorization": f"Bearer {get_store_token(merchant_id)}"}
    all_orders = []
    offset = 0
    while True:
        url = (f"{CLOVER_API_BASE}/v3/merchants/{merchant_id}/orders"
               f"?filter=createdTime>={start_ms}&filter=createdTime<={end_ms}"
               f"&expand=lineItems,payments,discounts,refunds&limit=100&offset={offset}")
        resp = await _request_with_retry(client, url, headers)
        if resp is None or resp.status_code != 200:
            break
        elements = resp.json().get("elements", [])
        all_orders.extend(elements)
        if len(elements) < 100:
            break
        offset += 100
    return all_orders

async def fetch_payments(merchant_id, start_ms, end_ms, client):
    headers = {"Authorization": f"Bearer {get_store_token(merchant_id)}"}
    all_payments = []
    offset = 0
    while True:
        url = (f"{CLOVER_API_BASE}/v3/merchants/{merchant_id}/payments"
               f"?filter=createdTime>={start_ms}&filter=createdTime<={end_ms}"
               f"&expand=refunds,additionalCharges,tender&limit=100&offset={offset}")
        resp = await _request_with_retry(client, url, headers)
        if resp is None or resp.status_code != 200:
            break
        elements = resp.json().get("elements", [])
        all_payments.extend(elements)
        if len(elements) < 100:
            break
        offset += 100
    return all_payments

MAX_ORDER_CENTS = 5_000_000  # 单笔订单上限 $50,000，超过视为异常数据
_anomaly_alerted = set()  # 已告警的异常订单 ID，防止重复告警


def _log_anomalous_orders(orders, store_name):
    """检测并记录异常订单，每个订单只告警一次。"""
    for o in orders:
        total = o.get("total", 0)
        order_id = o.get("id", "unknown")
        if abs(total) > MAX_ORDER_CENTS and order_id not in _anomaly_alerted:
            _anomaly_alerted.add(order_id)
            logger.warning(
                "⚠️ 异常订单已过滤 — 门店: %s, 订单ID: %s, 金额: $%s, 员工: %s",
                store_name, order_id, f"{total / 100:,.2f}",
                o.get("employee", {}).get("name", "N/A"),
            )


def compute_store_stats(orders, payments):
    # 过滤掉异常金额订单（如 $999,999.99 的测试/录入错误）
    orders = [o for o in orders if abs(o.get("total", 0)) <= MAX_ORDER_CENTS]

    group_totals = defaultdict(int)
    for order in orders:
        for item in order.get("lineItems", {}).get("elements", []):
            price = item.get("price", 0) * item.get("unitQty", 1)
            if abs(price) > MAX_ORDER_CENTS:
                continue
            item_cats = item.get("categories", {}).get("elements", [])
            group = classify_category(item_cats[0].get("name", "")) if item_cats else classify_category(item.get("name", ""))
            group_totals[group] += price

    order_count = len(orders)
    total_revenue = sum(o.get("total", 0) for o in orders)
    avg_order = total_revenue // order_count if order_count > 0 else 0

    refund_total = refund_count = discount_total = 0
    for order in orders:
        for r in order.get("refunds", {}).get("elements", []):
            refund_total += abs(r.get("amount", 0)); refund_count += 1
        for d in order.get("discounts", {}).get("elements", []):
            discount_total += abs(d.get("amount", 0))

    credit_total = cash_total = 0
    for p in payments:
        amount = p.get("amount", 0)
        tender = p.get("tender", {})
        label_key = tender.get("labelKey", "").lower()
        label = tender.get("label", "").lower()
        if "cash" in label_key or "cash" in label:
            cash_total += amount
        elif any(k in label_key or k in label for k in ("credit", "card")):
            credit_total += amount

    return {"category_totals": dict(group_totals), "order_count": order_count, "total_revenue": total_revenue,
            "avg_order": avg_order, "refund_total": refund_total, "refund_count": refund_count,
            "discount_total": discount_total, "credit_total": credit_total, "cash_total": cash_total}

# ── 数据抓取 ─────────────────────────────────────────────────

async def fetch_store_data(store, start_ms, end_ms, client):
    mid = store["merchant_id"]
    name = store["name"]
    display = STORE_DISPLAY.get(name, {"code": name.lower().replace(" ", "_"), "display_name_en": name})
    try:
        orders, payments = await asyncio.gather(
            fetch_orders(mid, start_ms, end_ms, client),
            fetch_payments(mid, start_ms, end_ms, client),
        )
        # 检测并过滤异常订单
        _log_anomalous_orders(orders, name)
        orders = [o for o in orders if abs(o.get("total", 0)) <= MAX_ORDER_CENTS]
        stats = compute_store_stats(orders, payments)
        employee_stats = defaultdict(lambda: {"revenue": 0, "orders": 0})
        for order in orders:
            emp_name = order.get("employee", {}).get("name", "Staff") or "Staff"
            employee_stats[emp_name]["revenue"] += order.get("total", 0)
            employee_stats[emp_name]["orders"] += 1

        rev_breakdown = {"repair": 0, "activation": 0, "accessory": 0, "sales": 0}
        for cat_name, amount in stats["category_totals"].items():
            rev_breakdown[CATEGORY_TO_DASHBOARD.get(cat_name, "sales")] += amount

        return {"store_name": name, "code": display["code"], "display_name_en": display["display_name_en"],
                "daily_revenue": stats["total_revenue"], "daily_orders": stats["order_count"],
                "avg_order": stats["avg_order"], "revenue_breakdown": rev_breakdown,
                "refund_total": stats["refund_total"], "refund_count": stats["refund_count"],
                "discount_total": stats["discount_total"], "credit_total": stats["credit_total"],
                "cash_total": stats["cash_total"], "employee_stats": dict(employee_stats), "error": None}
    except Exception as e:
        logger.error("获取 %s 数据失败: %s", name, e)
        return {"store_name": name, "code": display["code"], "display_name_en": display["display_name_en"],
                "daily_revenue": 0, "daily_orders": 0, "avg_order": 0,
                "revenue_breakdown": {"repair": 0, "activation": 0, "accessory": 0, "sales": 0},
                "employee_stats": {}, "error": str(e)}

async def fetch_monthly_revenue(store, month_start, end_ms, client):
    try:
        orders = await fetch_orders(store["merchant_id"], month_start, end_ms, client)
        return sum(o.get("total", 0) for o in orders if abs(o.get("total", 0)) <= MAX_ORDER_CENTS)
    except Exception as e:
        logger.error("获取 %s 月度数据失败: %s", store["name"], e)
        return 0

async def fetch_all_data(store_code="san_gabriel"):
    tz = get_tz()
    now = datetime.now(tz)
    day_start, day_end = day_range_ms(now)
    m_start = month_start_ms(now)

    async with httpx.AsyncClient() as client:
        daily_results = await asyncio.gather(*[fetch_store_data(s, day_start, day_end, client) for s in STORES])
        monthly_results = await asyncio.gather(*[fetch_monthly_revenue(s, m_start, day_end, client) for s in STORES])

    current_store = next((r for r in daily_results if r["code"] == store_code), daily_results[0] if daily_results else {})

    rankings = sorted([{"code": r["code"], "display_name_en": r["display_name_en"],
                         "daily_revenue": r["daily_revenue"] / 100, "daily_orders": r["daily_orders"]}
                        for r in daily_results], key=lambda x: x["daily_revenue"], reverse=True)

    month_data = sorted([{"display_name_en": r["display_name_en"], "total": monthly_results[i] / 100}
                          for i, r in enumerate(daily_results)], key=lambda x: x["total"], reverse=True)
    champion = month_data[0] if month_data else {"display_name_en": "-", "total": 0}

    cs = current_store
    breakdown = cs.get("revenue_breakdown", {})
    monthly_idx = next((i for i, s in enumerate(STORES) if STORE_DISPLAY.get(s["name"], {}).get("code") == store_code), 0)
    current_monthly = monthly_results[monthly_idx] / 100 if monthly_idx < len(monthly_results) else 0

    employee_rankings = sorted([{"name": n, "revenue": d["revenue"] / 100, "orders": d["orders"]}
                                 for n, d in cs.get("employee_stats", {}).items()],
                                key=lambda x: x["revenue"], reverse=True)

    return {
        "store": {"code": store_code, "display_name_en": cs.get("display_name_en", ""), "monthly_target": STORE_TARGETS.get(store_code, 65000)},
        "sales": {"daily_revenue": cs.get("daily_revenue", 0) / 100, "daily_orders": cs.get("daily_orders", 0), "monthly_revenue": current_monthly},
        "revenue_breakdown": {k: breakdown.get(k, 0) / 100 for k in ("repair", "activation", "accessory", "sales")},
        "rankings": rankings,
        "month_champion": champion,
        "employee_rankings": employee_rankings,
        "store_count": len(STORES),
        "updated_at": now.isoformat(),
    }

# ── 门店目标 & 评论数据 ───────────────────────────────────────
STORE_TARGETS = {
    "san_gabriel": 65000,
    "arcadia_1": 15000,
    "monterey_park": 50000,
    "arcadia_2": 40000,
    "irvine": 40000,
    "rancho_cucamonga": 40000,
    "las_vegas": 50000,
    "rowland_heights": 40000,
}

STORE_REVIEWS = {
    "san_gabriel": {"google": {"rating": 4.6, "total": 153}, "yelp": {"rating": 4.5, "total": 295}},
    "arcadia_1": {"google": {"rating": 4.5, "total": 142}, "yelp": {"rating": 4.7, "total": 611}},
    "las_vegas": {"google": {"rating": 4.8, "total": 77}},
}

# ── 缓存 ─────────────────────────────────────────────────────
cache_lock = Lock()
cached_data = {}
cached_time = {}
CACHE_TTL = 30

def get_data_sync(store_code="san_gabriel"):
    global cached_data, cached_time
    with cache_lock:
        if store_code in cached_data and store_code in cached_time and (datetime.now().timestamp() - cached_time[store_code]) < CACHE_TTL:
            return cached_data[store_code]
    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(asyncio.wait_for(fetch_all_data(store_code), timeout=30))
    except asyncio.TimeoutError:
        logger.error("Clover API 超时 (30s), store=%s", store_code)
        with cache_lock:
            if store_code in cached_data:
                return cached_data[store_code]
        data = {"store": {"code": store_code, "display_name_en": store_code, "monthly_target": STORE_TARGETS.get(store_code, 65000)},
                "sales": {"daily_revenue": 0, "daily_orders": 0, "monthly_revenue": 0},
                "revenue_breakdown": {"repair": 0, "activation": 0, "accessory": 0, "sales": 0},
                "rankings": [], "month_champion": {}, "employee_rankings": [], "store_count": len(STORES), "updated_at": datetime.now(get_tz()).isoformat()}
    finally:
        loop.close()
    # 注入看板数据
    try:
        data["items"] = get_today_items(store_code)
        data["notices"] = get_active_notices(store_code)
    except Exception as e:
        logger.error("获取看板数据失败: %s", e)
        data.setdefault("items", [])
        data.setdefault("notices", [])

    # 评论数据（Yelp / Google / 微信）
    try:
        data.setdefault("reviews", {})
        # 注入门店 Yelp/Google 评论数据
        store_reviews = STORE_REVIEWS.get(store_code, {})
        if "google" in store_reviews:
            data["reviews"]["google"] = store_reviews["google"]
        if "yelp" in store_reviews:
            data["reviews"]["yelp"] = store_reviews["yelp"]
        # 微信好友实时数据
        wechat_data = get_wechat_total(store_code)
        data["reviews"]["wechat"] = {"total": wechat_data["total"], "today_added": wechat_data["today_added"]}
    except Exception as e:
        logger.error("获取评论数据失败: %s", e)

    with cache_lock:
        cached_data[store_code] = data
        cached_time[store_code] = datetime.now().timestamp()
    return data

# ── HTTP Server ──────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/dashboard"):
            store_code = "san_gabriel"
            if "?" in self.path:
                for p in self.path.split("?")[1].split("&"):
                    if p.startswith("store="):
                        store_code = p.split("=")[1]
            try:
                data = get_data_sync(store_code)
                self._json_response(200, data)
            except Exception as e:
                logger.error("API error: %s", e)
                self._json_response(500, {"error": str(e)})
        else:
            self._serve_static()

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _serve_static(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "" or path == "/":
            path = "/index.html"
        file_path = STATIC_DIR / path.lstrip("/")
        if file_path.is_file():
            ext = file_path.suffix.lower()
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css",
                ".js": "application/javascript",
                ".json": "application/json",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml",
                ".ico": "image/x-icon",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            self.send_response(200)
            self.send_header("Content-Type", content_types.get(ext, "application/octet-stream"))
            self.send_header("Cache-Control", "no-cache" if ext == ".html" else "public, max-age=3600")
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        logger.info("%s %s", self.address_string(), format % args)


if __name__ == "__main__":
    init_db()
    port = 8889
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    logger.info("Dashboard server running on http://0.0.0.0:%d", port)
    logger.info("Dashboard: http://0.0.0.0:%d/", port)
    logger.info("API: http://0.0.0.0:%d/api/dashboard?store=san_gabriel", port)
    logger.info("Stores: %d", len(STORES))
    for s in STORES:
        logger.info("  - %s (%s...)", s["name"], s["merchant_id"][:8] if s["merchant_id"] else "NO_MID")
    server.serve_forever()
