#!/usr/bin/env python3
"""Patch /opt/dashboard/server.py v2: add create endpoints for admin panel."""
from pathlib import Path

f = Path("/opt/dashboard/server.py")
code = f.read_text()

# 1. Add add_item, add_notice to db imports (idempotent check)
if "add_item, add_notice" not in code:
    code = code.replace(
        "mark_done, delete_item, deactivate_notice)",
        "mark_done, delete_item, deactivate_notice,\n"
        "                add_item, add_notice)",
    )

# 2. Add create routes before existing POST routes (idempotent check)
if "/api/admin/items/create" not in code:
    code = code.replace(
        '        if path.startswith("/api/admin/items/") and path.endswith("/done"):',
        '        if path == "/api/admin/items/create":\n'
        '            store = body.get("store", "san_gabriel")\n'
        '            item_id = add_item(store, body)\n'
        '            self._json_response(200, {"ok": True, "id": item_id})\n'
        '        elif path == "/api/admin/notices/create":\n'
        '            store = body.get("store", "san_gabriel")\n'
        '            notice_id = add_notice(store, body)\n'
        '            self._json_response(200, {"ok": True, "id": notice_id})\n'
        '        elif path.startswith("/api/admin/items/") and path.endswith("/done"):',
    )

f.write_text(code)
print("OK - server.py patched with create endpoints")
