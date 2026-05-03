#!/usr/bin/env python3
"""Patch /opt/dashboard/server.py to add admin API routes."""
from pathlib import Path

f = Path("/opt/dashboard/server.py")
code = f.read_text()

# 1. Fix db imports
code = code.replace(
    "from db import get_today_items, get_active_notices, init_db",
    "from db import (get_today_items, get_active_notices, init_db,\n"
    "                get_items_history, get_all_notices_admin, get_admin_stats,\n"
    "                mark_done, delete_item, deactivate_notice)",
)

# 2. Add parse_params helper before class
code = code.replace(
    "class DashboardHandler(BaseHTTPRequestHandler):",
    "def _parse_params(path):\n"
    "    params = {}\n"
    '    if "?" in path:\n'
    '        for p in path.split("?")[1].split("&"):\n'
    '            if "=" in p:\n'
    '                k, v = p.split("=", 1)\n'
    "                params[k] = v\n"
    "    return params\n"
    "\n"
    "\n"
    "class DashboardHandler(BaseHTTPRequestHandler):",
)

# 3. Replace do_GET to add admin routes
OLD_GET = '''    def do_GET(self):
        if self.path.startswith("/api/dashboard"):
            store_code = "san_gabriel"
            if "?" in self.path:
                for p in self.path.split("?")[1].split("&"):
                    if p.startswith("store="):
                        store_code = p.split("=")[1]
            try:
                data = get_data_sync(store_code); data["items"] = get_today_items(store_code); data["notices"] = get_active_notices(store_code)
                self._json_response(200, data)
            except Exception as e:
                logger.error("API error: %s", e)
                self._json_response(500, {"error": str(e)})
        else:
            self._serve_static()'''

NEW_GET = '''    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/dashboard":
            params = _parse_params(self.path)
            store_code = params.get("store", "san_gabriel")
            try:
                data = get_data_sync(store_code); data["items"] = get_today_items(store_code); data["notices"] = get_active_notices(store_code)
                self._json_response(200, data)
            except Exception as e:
                logger.error("API error: %s", e)
                self._json_response(500, {"error": str(e)})
        elif path == "/api/admin/items":
            params = _parse_params(self.path)
            store = params.get("store", "san_gabriel")
            days = int(params.get("days", "7"))
            item_type = params.get("type") or None
            status = params.get("status") or None
            self._json_response(200, get_items_history(store, days, item_type, status))
        elif path == "/api/admin/notices":
            params = _parse_params(self.path)
            self._json_response(200, get_all_notices_admin(params.get("store", "san_gabriel")))
        elif path == "/api/admin/stats":
            params = _parse_params(self.path)
            self._json_response(200, get_admin_stats(params.get("store", "san_gabriel")))
        elif path == "/admin":
            admin_file = Path(__file__).parent / "admin.html"
            if admin_file.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(admin_file.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self._serve_static()

    def do_POST(self):
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}
        if path.startswith("/api/admin/items/") and path.endswith("/done"):
            item_id = int(path.split("/")[4])
            self._json_response(200, {"ok": mark_done(item_id, body.get("done_by", "Admin"))})
        elif path.startswith("/api/admin/items/") and path.endswith("/delete"):
            item_id = int(path.split("/")[4])
            self._json_response(200, {"ok": delete_item(item_id)})
        elif path.startswith("/api/admin/notices/") and path.endswith("/deactivate"):
            notice_id = int(path.split("/")[4])
            self._json_response(200, {"ok": deactivate_notice(notice_id)})
        else:
            self._json_response(404, {"error": "not found"})'''

code = code.replace(OLD_GET, NEW_GET)

# 4. Update OPTIONS to include POST
code = code.replace(
    'Allow-Methods", "GET, OPTIONS"',
    'Allow-Methods", "GET, POST, OPTIONS"',
)

f.write_text(code)
print("OK - server.py patched successfully")
