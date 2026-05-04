"""
AR1 门店 Dashboard Bot — Telegram 长轮询
接收群消息 → Claude 分类 → 存入 SQLite → 看板显示

启动: python3 dashboard_bot_ar1.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date

import httpx

from db import add_item, add_notice, get_today_items, get_active_notices, mark_done, delete_item, get_item, init_db, get_wechat_total, deactivate_notice
from classifier import classify_message

# ── 配置 ─────────────────────────────────────────────────────

AR1_BOT_TOKEN = "8194812093:AAHQVT1uGEqqFqQwZ3cz8VkMNnZgM_b_v-s"
AR1_STORE_CODE = "arcadia_1"
TELEGRAM_API = f"https://api.telegram.org/bot{AR1_BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_bot_ar1.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

TYPE_LABELS = {
    "customer_followup": "📞 客户跟进",
    "incoming_inventory": "📦 到货提醒",
    "handoff": "🔄 交班事项",
    "repair_pending": "🔧 维修等待",
    "todo": "✏️ 待办",
    "notice": "📢 公告",
    "wechat_report": "💚 微信报备",
}

# ── Telegram 消息发送 ────────────────────────────────────────

SEND_MAX_RETRIES = 3


async def send_message(chat_id: str | int, text: str, reply_to: int = None, reply_markup: dict = None) -> bool:
    """发送 Telegram 消息，失败重试。"""
    payload = {"chat_id": str(chat_id), "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    for attempt in range(SEND_MAX_RETRIES):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
                if resp.status_code == 200:
                    return True
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    await asyncio.sleep(retry_after)
                    continue
                logger.error("发送失败 [%s]: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("发送异常: %s", e)
        if attempt < SEND_MAX_RETRIES - 1:
            await asyncio.sleep(2 * (attempt + 1))
    return False


async def answer_callback(callback_query_id: str, text: str = "") -> None:
    """应答 callback query（消除按钮加载状态）"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={
                "callback_query_id": callback_query_id,
                "text": text,
            }, timeout=10)
    except Exception as e:
        logger.error("answerCallback 异常: %s", e)


async def edit_message(chat_id: str | int, message_id: int, text: str, reply_markup: dict = None) -> None:
    """编辑已发送的消息"""
    payload = {"chat_id": str(chat_id), "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error("editMessage 异常: %s", e)


# ── 命令处理 ─────────────────────────────────────────────────

async def cmd_done(chat_id: str, args: str, sender_name: str) -> None:
    """标记看板项完成"""
    try:
        item_id = int(args.strip())
    except (ValueError, TypeError):
        await send_message(chat_id, "用法: /done <ID>\n例: /done 3")
        return

    if mark_done(item_id, sender_name):
        await send_message(chat_id, f"✅ #{item_id} 已标记完成 (by {sender_name})")
    else:
        await send_message(chat_id, f"❌ #{item_id} 未找到或已完成")


async def cmd_delete(chat_id: str, args: str) -> None:
    """删除看板项"""
    try:
        item_id = int(args.strip())
    except (ValueError, TypeError):
        await send_message(chat_id, "用法: /delete <ID>\n例: /delete 3")
        return

    if delete_item(item_id):
        await send_message(chat_id, f"🗑 #{item_id} 已删除")
    else:
        await send_message(chat_id, f"❌ #{item_id} 未找到")


async def cmd_list(chat_id: str) -> None:
    """显示今日看板摘要"""
    items = get_today_items(AR1_STORE_CODE)
    if not items:
        await send_message(chat_id, "📋 今日看板为空")
        return

    lines = [f"📋 今日看板 — {date.today().isoformat()} ({len(items)}项)", ""]
    for item in items:
        urgent = "🔴 " if item.get("urgent") else ""
        time_str = f" ⏰{item['due_time']}" if item.get("due_time") else ""
        lines.append(f"#{item['id']} {urgent}{item['display_emoji']} {item['content']}{time_str}")

    await send_message(chat_id, "\n".join(lines))


async def cmd_notices(chat_id: str) -> None:
    """显示当前公告"""
    notices = get_active_notices(AR1_STORE_CODE)
    if not notices:
        await send_message(chat_id, "📢 当前无公告")
        return

    lines = ["📢 当前公告:", ""]
    for n in notices:
        lines.append(f"#{n['id']} {n['display_emoji']} {n['content']}")

    await send_message(chat_id, "\n".join(lines))


async def cmd_wechat(chat_id: str, args: str, msg_id: int, sender_name: str) -> None:
    """快速报备微信好友新增"""
    try:
        amount = int(args.strip())
    except (ValueError, TypeError):
        await send_message(chat_id, "用法: /wechat <数量>\n例: /wechat 5")
        return
    if amount <= 0:
        await send_message(chat_id, "❌ 数量必须大于0")
        return

    item = {
        "type": "wechat_report",
        "content": f"今日新增{amount}人",
        "display_emoji": "💚",
        "due_date": date.today().isoformat(),
        "creator_name": sender_name,
        "telegram_msg_id": msg_id,
        "telegram_chat_id": str(chat_id),
        "meta": {"amount": amount},
    }
    add_item(AR1_STORE_CODE, item)
    wechat = get_wechat_total(AR1_STORE_CODE)
    await send_message(
        chat_id,
        f"💚 微信好友已记录: +{amount}人 (今日+{wechat['today_added']}，累计{wechat['total']:,})",
        reply_to=msg_id,
    )


async def cmd_help(chat_id: str) -> None:
    text = (
        "📖 AR1 Dashboard Bot 命令\n"
        "\n"
        "发送自然语言消息即可自动添加到看板\n"
        "例: \"王先生下午3点来取iPhone 15 Pro\"\n"
        "\n"
        "/list — 查看今日看板\n"
        "/notices — 查看公告\n"
        "/done <ID> — 标记完成\n"
        "/delete <ID> — 删除看板项\n"
        "/wechat <数量> — 快速报备微信好友新增\n"
        "/help — 显示本帮助"
    )
    await send_message(chat_id, text)


# ── Inline 按钮处理 ──────────────────────────────────────────

def make_done_button(item_id: int) -> dict:
    """生成 '✅ 完成' 和 '🗑 删除' inline 按钮"""
    return {
        "inline_keyboard": [[
            {"text": "✅ 完成", "callback_data": f"done:{item_id}"},
            {"text": "🗑 删除", "callback_data": f"del:{item_id}"},
        ]]
    }


async def handle_callback(callback_query: dict) -> None:
    """处理 inline 按钮点击"""
    cb_id = callback_query.get("id", "")
    data = callback_query.get("data", "")
    msg = callback_query.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    message_id = msg.get("message_id")
    from_user = callback_query.get("from", {})
    sender_name = from_user.get("first_name", "")
    if from_user.get("last_name"):
        sender_name += " " + from_user["last_name"]
    sender_name = sender_name.strip() or "Unknown"

    if data.startswith("done:"):
        item_id = int(data.split(":")[1])
        if mark_done(item_id, sender_name):
            await answer_callback(cb_id, f"#{item_id} 已完成!")
            old_text = msg.get("text", "")
            await edit_message(chat_id, message_id, old_text + f"\n\n✅ 已完成 (by {sender_name})")
        else:
            await answer_callback(cb_id, f"#{item_id} 未找到或已完成")

    elif data.startswith("del:"):
        item_id = int(data.split(":")[1])
        if delete_item(item_id):
            await answer_callback(cb_id, f"#{item_id} 已删除!")
            old_text = msg.get("text", "")
            await edit_message(chat_id, message_id, old_text + f"\n\n🗑 已删除 (by {sender_name})")
        else:
            await answer_callback(cb_id, f"#{item_id} 未找到")

    elif data.startswith("deln:"):
        notice_id = int(data.split(":")[1])
        if deactivate_notice(notice_id):
            await answer_callback(cb_id, f"公告 #{notice_id} 已删除!")
            old_text = msg.get("text", "")
            await edit_message(chat_id, message_id, old_text + f"\n\n🗑 公告已删除 (by {sender_name})")
        else:
            await answer_callback(cb_id, f"公告 #{notice_id} 未找到")

    else:
        await answer_callback(cb_id)


# ── 自然语言消息处理 ─────────────────────────────────────────

async def handle_natural_message(chat_id: str, msg_id: int, text: str, sender_name: str) -> None:
    """自然语言消息 → 分类 → 存储 → 回复确认（带完成按钮）"""
    result = classify_message(text, sender_name)

    if isinstance(result, list):
        items = result
    else:
        items = [result]

    for item in items:
        await _process_one_item(chat_id, msg_id, item, sender_name)


async def _process_one_item(chat_id: str, msg_id: int, result: dict, sender_name: str) -> None:
    """处理单条分类结果"""
    if result.get("skip"):
        logger.info("跳过非工作消息")
        return

    if not result.get("due_date"):
        result["due_date"] = date.today().isoformat()

    result["creator_name"] = sender_name
    result["telegram_msg_id"] = msg_id
    result["telegram_chat_id"] = str(chat_id)

    msg_type = result.get("type", "todo")
    label = TYPE_LABELS.get(msg_type, msg_type)

    if msg_type == "notice":
        notice_id = add_notice(AR1_STORE_CODE, result)
        await send_message(
            chat_id,
            f"✅ 公告已发布 #{notice_id}: {result.get('content', '')}",
            reply_to=msg_id,
            reply_markup={"inline_keyboard": [[{"text": "🗑 删除公告", "callback_data": f"deln:{notice_id}"}]]},
        )
    elif msg_type == "wechat_report":
        meta = result.get("meta", {})
        raw_amount = int(meta.get("amount") or 0)
        source_mode = meta.get("source", "increment")

        if source_mode == "total":
            current = get_wechat_total(AR1_STORE_CODE)
            amount = max(0, raw_amount - current["total"])
            if amount == 0:
                await send_message(chat_id, f"💚 当前微信好友已是 {current['total']:,}，无新增", reply_to=msg_id)
                return
            result["meta"]["amount"] = amount
            result["content"] = f"今日新增{amount}人"
        else:
            amount = raw_amount

        item_id = add_item(AR1_STORE_CODE, result)
        wechat = get_wechat_total(AR1_STORE_CODE)
        await send_message(
            chat_id,
            f"💚 微信好友已记录: +{amount}人 (今日+{wechat['today_added']}，累计{wechat['total']:,})",
            reply_to=msg_id,
        )
    else:
        item_id = add_item(AR1_STORE_CODE, result)
        urgent_tag = " 🔴急" if result.get("urgent") else ""
        time_tag = f" ⏰{result['due_time']}" if result.get("due_time") else ""
        await send_message(
            chat_id,
            f"✅ 看板已更新 #{item_id}: {label} {result.get('content', '')}{time_tag}{urgent_tag}",
            reply_to=msg_id,
            reply_markup=make_done_button(item_id),
        )


# ── 消息路由 ─────────────────────────────────────────────────

def parse_command(text: str) -> tuple:
    """解析命令和参数"""
    text = text.strip()
    if " " in text:
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0].lower()
        args = parts[1].strip()
    else:
        cmd = text.split("@")[0].lower()
        args = ""
    return cmd, args


async def handle_message(chat_id: str, msg_id: int, user_id: str, text: str, sender_name: str) -> None:
    """消息路由"""
    if text.startswith("/"):
        cmd, args = parse_command(text)
        if cmd == "/done":
            await cmd_done(chat_id, args, sender_name)
        elif cmd == "/delete":
            await cmd_delete(chat_id, args)
        elif cmd == "/list":
            await cmd_list(chat_id)
        elif cmd == "/notices":
            await cmd_notices(chat_id)
        elif cmd == "/wechat":
            await cmd_wechat(chat_id, args, msg_id, sender_name)
        elif cmd in ("/help", "/start"):
            await cmd_help(chat_id)
    else:
        await handle_natural_message(chat_id, msg_id, text, sender_name)


# ── Telegram 长轮询 ──────────────────────────────────────────

async def poll_updates() -> None:
    """长轮询监听 Telegram 消息"""
    offset = 0
    consecutive_errors = 0

    init_db()
    logger.info("AR1 Dashboard Bot 已启动 (store: %s)", AR1_STORE_CODE)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await client.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=40,
                )
                if resp.status_code != 200:
                    logger.warning("getUpdates 返回 %s", resp.status_code)
                    consecutive_errors += 1
                    await asyncio.sleep(min(5 * consecutive_errors, 60))
                    continue

                consecutive_errors = 0
                updates = resp.json().get("result", [])

                for update in updates:
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        asyncio.create_task(handle_callback(update["callback_query"]))
                        continue

                    msg = update.get("message", {})
                    chat = msg.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    user_id = str(msg.get("from", {}).get("id", ""))
                    text = msg.get("text", "").strip()
                    msg_id = msg.get("message_id")

                    from_user = msg.get("from", {})
                    sender_name = from_user.get("first_name", "")
                    if from_user.get("last_name"):
                        sender_name += " " + from_user["last_name"]
                    sender_name = sender_name.strip() or "Unknown"

                    if not chat_id or not text:
                        continue

                    logger.info("收到消息: chat=%s user=%s sender=%s text=%s", chat_id, user_id, sender_name, text[:80])
                    asyncio.create_task(handle_message(chat_id, msg_id, user_id, text, sender_name))

            except Exception as e:
                consecutive_errors += 1
                wait = min(5 * consecutive_errors, 60)
                logger.error("轮询异常: %s (连续第%d次，等待%ds)", e, consecutive_errors, wait)
                await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(poll_updates())
