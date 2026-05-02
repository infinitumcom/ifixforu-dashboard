"""
Dashboard 消息分类器 — 调用 Claude Haiku 将自然语言转为结构化看板数据
"""

import json
import logging
import os
from datetime import date

from anthropic import Anthropic

logger = logging.getLogger(__name__)

# API key 从环境变量或 .env 读取
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

client = Anthropic(api_key=API_KEY) if API_KEY else None

SYSTEM_PROMPT = """你是手机维修门店看板助手。根据员工发送的消息，提取结构化信息用于门店看板显示。

分类为以下类型之一：
1. customer_followup (📞) — 客户取机/回访/到店
2. incoming_inventory (📦) — 到货/物流/快递
3. handoff (🔄) — 交班事项/信息传达/注意事项
4. repair_pending (🔧) — 维修等待（等客户确认/等配件）
5. todo (✏️) — 待办任务/需要做的事
6. notice (📢) — 公告/通知/重要提醒（适合显示在跑马灯）

返回严格 JSON 格式：
{
  "type": "类型标识",
  "content": "简洁的看板显示文本（中文，20字以内）",
  "display_emoji": "对应emoji",
  "due_date": "YYYY-MM-DD 或 null",
  "due_time": "HH:MM 或 null",
  "urgent": false,
  "meta": {
    "ticket": "票号或null",
    "phone": "手机型号或null",
    "amount": 金额数字或null,
    "paid": false,
    "source": "来源或null"
  }
}

规则：
- content 要简洁，适合看板显示，保留关键信息（人名、时间、型号、票号）
- 如果提到具体时间，提取 due_date 和 due_time
- 如果没有明确日期，due_date 设为今天
- 如果消息提到"急"、"尽快"、"马上"，urgent 设为 true
- 如果消息不像工作内容（纯闲聊、表情包、无意义内容），返回 {"skip": true}
- meta 中的字段，没有的设�� null
- amount 是数字，不带 $ 符号
- 如果一条消息包含多个独立任务，返回 JSON 数组 [item1, item2, ...]
- 如果只有一个任务，返回单个 JSON 对象
- 只返回 JSON，不要其他文字"""


def classify_message(text: str, sender_name: str = "") -> dict:
    """
    分类消息，返回结构化 dict。
    失败时返回 fallback（type=todo, 原文作为 content）。
    """
    if not client:
        logger.error("ANTHROPIC_API_KEY 未设置，使用 fallback")
        return _fallback(text, sender_name)

    today = date.today().isoformat()
    user_msg = f"今天日期: {today}\n发送者: {sender_name}\n消息: {text}" if sender_name else f"今天日期: {today}\n消息: {text}"

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()

        # 尝试提取 JSON（可能被 ``` 包裹）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        logger.info("分类结果: %s", json.dumps(result, ensure_ascii=False))
        return result

    except json.JSONDecodeError as e:
        logger.error("JSON 解析失败: %s — raw: %s", e, raw[:200])
        return _fallback(text, sender_name)
    except Exception as e:
        logger.error("Claude API 调用失败: %s", e)
        return _fallback(text, sender_name)


def _fallback(text: str, sender_name: str = "") -> dict:
    """API 失败时的 fallback — 作为 todo 保存"""
    content = text[:50] if len(text) > 50 else text
    return {
        "type": "todo",
        "content": content,
        "display_emoji": "✏️",
        "due_date": None,
        "due_time": None,
        "urgent": False,
        "meta": {},
    }
