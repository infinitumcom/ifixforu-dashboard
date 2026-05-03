# iFixForU Dashboard — 系统架构文档

> 最后更新: 2026-05-02

## 一、系统概览

iFixForU Dashboard 是一套面向手机维修连锁门店的实时运营看板系统。通过 Clover POS 获取营业数据，通过 Telegram Bot 接收员工发布的看板内容，最终在门店 Fire TV 大屏上展示。

```
员工发消息 → Telegram Group → Bot (长轮询)
  → Claude AI 自然语言分类
  → SQLite 存储
  → API Server 返回 JSON
  → Fire TV Dashboard 显示
```

## 二、服务器信息

| 项目 | 值 |
|------|-----|
| 服务器 IP | `64.62.248.68` |
| 系统 | Debian GNU/Linux |
| 管理面板 | 宝塔 (BT-Panel) |
| 部署路径 | `/opt/dashboard/` |
| Python venv | `/opt/dashboard-venv/` |
| 开发路径 | `/root/ifixforu-dashboard/` (Bot 运行) |
| API 端口 | `8889` |
| GitHub | `infinitumcom/ifixforu-dashboard` |

## 三、文件清单与用途

### 服务端文件（部署在 `/opt/dashboard/`）

| 文件 | 用途 |
|------|------|
| `server.py` | 生产 API 服务器 — 拉取 Clover 数据 + 服务静态文件 |
| `dashboard_bot.py` | Telegram Bot — 长轮询接收消息 |
| `db.py` | SQLite 数据层 — 建表/CRUD |
| `classifier.py` | Claude AI 分类器 — 自然语言→结构化数据 |
| `dashboard.db` | SQLite 数据库文件 |
| `.env` | 环境变量（Clover token、Anthropic API key） |
| `static/index.html` | 前端单页面应用 |

### APK 工程（`firetv-app/`）

| 文件 | 用途 |
|------|------|
| `MainActivity.java` | WebView 容器 + CSS/JS 注入（竖屏布局、字体、分类修改） |
| `WatchdogService.java` | 守护服务 — 每 10 秒检查 App 是否在前台 |
| `BootReceiver.java` | 开机自启 — 收到 BOOT_COMPLETED 启动看板 |
| `AndroidManifest.xml` | 权限声明、Leanback 启动器 |

### Systemd 服务

| 服务 | 文件 | 状态 |
|------|------|------|
| `dashboard.service` | API Server | 运行中 (active) |
| `dashboard-bot.service` | Telegram Bot | 已禁用 (disabled)* |

> *Bot 目前从 `/root/ifixforu-dashboard/` 通过 nohup 运行，使用 `/root/ifixforu-dashboard/venv/` 虚拟环境。数据库通过符号链接指向 `/opt/dashboard/dashboard.db`。

## 四、数据流详解

### 4.1 Clover POS → API Server

```
Clover POS (8家门店)
  ↓ HTTP API (orders + payments)
api_server.py (60秒缓存)
  ↓ 计算营收、排行、员工业绩
  ↓ 转换 cents → dollars
JSON 响应
```

**API 端点:** `GET /api/dashboard?store=san_gabriel`

**响应结构:**
```json
{
  "store": { "code": "san_gabriel", "display_name_en": "San Gabriel", "monthly_target": 65000 },
  "sales": { "daily_revenue": 2767.0, "daily_orders": 20, "monthly_revenue": 3770.0 },
  "revenue_breakdown": { "repair": 1170.0, "activation": 1477.0, "accessory": 125.0, "sales": 0.0 },
  "rankings": [{ "code": "san_gabriel", "display_name_en": "San Gabriel", "daily_revenue": 2767.0, "daily_orders": 20 }],
  "month_champion": { "display_name_en": "San Gabriel", "total": 3770.0 },
  "employee_rankings": [{ "name": "Staff", "revenue": 2767.0, "orders": 20 }],
  "items": [],
  "notices": [],
  "store_count": 8,
  "updated_at": "2026-05-02T20:27:16-07:00"
}
```

**缓存策略:**
- Clover 数据: 60 秒缓存（减少 API 调用）
- items/notices: 每次请求实时查询 SQLite（不走缓存）

### 4.2 Telegram Bot → SQLite

```
员工在 Telegram 群发消息
  ↓ Bot 长轮询接收 (30s timeout)
classifier.py 调用 Claude Haiku
  ↓ 返回结构化分类
db.py 写入 SQLite
  ↓ Bot 回复确认（带完成/删除按钮）
```

**Bot Token:** `8668095541:AAEJw71XFFu_VTociX-Xam1D0xsKHjrIe2Y`
**Bot 用户名:** `@IFIXFORU_SG_bot`
**门店代码:** `san_gabriel`（硬编码）

**支持的命令:**

| 命令 | 功能 |
|------|------|
| 自然语言消息 | 自动分类并添加到看板 |
| `/list` | 查看今日看板 |
| `/notices` | 查看公告 |
| `/done <ID>` | 标记完成 |
| `/delete <ID>` | 删除看板项 |
| `/help` | 帮助 |

### 4.3 SQLite 数据库

**数据库文件:** `/opt/dashboard/dashboard.db`
**符号链接:** `/root/ifixforu-dashboard/dashboard.db → /opt/dashboard/dashboard.db`

**board_items 表:**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| store_code | TEXT | 门店代码 (default: san_gabriel) |
| type | TEXT | customer_followup / incoming_inventory / handoff / repair_pending / todo |
| content | TEXT | 看板内容（中文，≤20字） |
| display_emoji | TEXT | 显示 emoji |
| due_date | TEXT | YYYY-MM-DD |
| due_time | TEXT | HH:MM |
| status | TEXT | pending / done |
| urgent | INTEGER | 0/1 |
| creator_name | TEXT | Telegram 发送者 |
| done_by | TEXT | 完成操作者 |
| meta_ticket | TEXT | 工单号 |
| meta_phone | TEXT | 手机型号 |
| meta_amount | REAL | 金额 |
| meta_paid | INTEGER | 是否已付 |
| meta_source | TEXT | 来源 |
| telegram_msg_id | INTEGER | Telegram 消息 ID |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**notices 表:**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| store_code | TEXT | 门店代码 |
| content | TEXT | 公告内容 |
| display_emoji | TEXT | 默认 📢 |
| priority | INTEGER | 优先级 |
| active | INTEGER | 是否有效 |
| creator_name | TEXT | 创建者 |
| created_at | TEXT | 创建时间 |
| expires_at | TEXT | 过期时间 |

### 4.4 Claude AI 分类器

**模型:** `claude-haiku-4-5-20251001`（低成本、快速）
**API Key:** 通过 `.env` 文件的 `ANTHROPIC_API_KEY` 提供

**分类类型:**

| 类型 | Emoji | 说明 |
|------|-------|------|
| customer_followup | 📞 | 客户取机/回访 |
| incoming_inventory | 📦 | 到货/物流 |
| handoff | 🔄 | 交班事项 |
| repair_pending | 🔧 | 维修等待 |
| todo | ✏️ | 待办任务 |
| notice | 📢 | 公告（显示在跑马灯） |

**输入:** 自然语言消息 + 发送者姓名
**输出:** JSON（type, content, emoji, due_date, meta 等）
**特殊处理:** 闲聊/表情返回 `{"skip": true}`；一条消息可分出多个任务

### 4.5 前端 → Fire TV

```
index.html (单页面应用)
  ↓ loadData() 每 5 秒轮询 API
  ↓ 合并 live 数据 + MOCK_DATA
  ↓ render() 更新 DOM
  ↓
Fire TV APK (WebView)
  ↓ injectHelperScripts() 注入 CSS/JS
  ↓ 竖屏布局适配、字体调大、分类修改
  ↓ 守护服务 + 开机自启
```

## 五、Fire TV APK 注入修改清单

APK 通过 `injectHelperScripts()` 注入 JS/CSS 对前端进行以下修改：

| 修改项 | 说明 |
|--------|------|
| CONFIG.API_BASE | 设为 `http://64.62.248.68:8889` |
| CONFIG.REFRESH_INTERVAL | 15s → 5s |
| MOCK_DATA.items/notices | 清空（避免显示测试数据） |
| `#app` animation | 禁用 pixel-shift 动画（防止覆盖旋转） |
| Grid 9行布局 | 80/54/46/240/1fr/115/108/270/18px |
| renderBoard | 按 ID 倒序、过滤已完成、最多 15 条 |
| renderRecommendations | 每类限 1 条 |
| renderRankingsFixed | 过滤 Alhambra 门店（显示 8 家） |
| renderShift | 中文标签 + 明日当班 |
| renderRevenue | 5 列分类（维修/开卡/充值/销售/其他） |
| Pipeline "质检" | 改为"主板维修待取" |
| 字体大小 | 看板文字 21px、emoji 28px、meta 15px |
| WebView 启动 | 先隐藏，注入完成 800ms 后显示（防闪屏） |

## 六、支持的门店

| 代码 | 名称 | 排班缩写 |
|------|------|----------|
| san_gabriel | San Gabriel | SG |
| monterey_park | Monterey Park | MPK |
| arcadia_1 | Arcadia 1 | AR |
| arcadia_2 | Arcadia 2 | AR3 |
| irvine | Irvine | IR |
| rancho_cucamonga | Rancho Cucamonga | RANCHO |
| las_vegas | Las Vegas | NV |
| rowland_heights | Rowland Heights | RH |

> 当前只有 San Gabriel 门店部署了 Fire TV + Telegram Bot。

## 七、关键配置值

| 配置 | 值 | 位置 |
|------|-----|------|
| API 端口 | 8889 | server.py |
| Clover 缓存 TTL | 60 秒 | server.py |
| 前端刷新间隔 | 5 秒（APK 注入） | MainActivity.java |
| APK 全量刷新 | 5 分钟 | MainActivity.java |
| 守护检查间隔 | 10 秒 | WatchdogService.java |
| Bot 轮询超时 | 30 秒 | dashboard_bot.py |
| Claude 模型 | claude-haiku-4-5-20251001 | classifier.py |
| 月度目标 | $65,000 | index.html |
| 看板项显示上限 | 15 条 | APK 注入 |

## 八、运行方式

### 生产环境（服务器）

```bash
# API Server — systemd 管理，自动重启
systemctl status dashboard.service

# Telegram Bot — 手动运行（systemd 已禁用）
cd /root/ifixforu-dashboard
nohup ./venv/bin/python3 dashboard_bot.py >> dashboard_bot.log 2>&1 &

# 查看 Bot 日志
tail -f /root/ifixforu-dashboard/dashboard_bot.log
```

### 开发环境（本地 Mac）

```bash
# 构建 APK
cd /Users/Apple/Projects/ifixforu-dashboard/firetv-app
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
./gradlew assembleDebug

# 安装到 Fire TV
export PATH="$PATH:/Users/Apple/Library/Android/sdk/platform-tools"
adb -s 10.0.0.50:5555 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s 10.0.0.50:5555 shell am force-stop com.ifixforu.dashboard
adb -s 10.0.0.50:5555 shell am start -n com.ifixforu.dashboard/.MainActivity
```

### Fire TV 设备

| 项目 | 值 |
|------|-----|
| 设备 | Amazon Fire TV |
| IP | 10.0.0.50:5555 (ADB) |
| 分辨率 | 3840x2160 (4K), DPR=4, 逻辑 960x540 |
| 安装方式 | 竖屏壁挂 |
| App 包名 | com.ifixforu.dashboard |
