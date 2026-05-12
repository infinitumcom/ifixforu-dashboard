#!/bin/bash
# Fire TV Dashboard 守护脚本
# 每 10 秒检查 Dashboard app 是否在前台，不在则自动启动
# 用法: launchd 自动运行，或手动 ./firetv-watchdog.sh

ADB="$HOME/Library/Android/sdk/platform-tools/adb"
DEVICE="10.0.0.50:5555"
PACKAGE="com.ifixforu.dashboard"
ACTIVITY="$PACKAGE/.MainActivity"
CHECK_INTERVAL=10

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1"
}

# 确保 ADB 连接
ensure_connected() {
    $ADB connect "$DEVICE" >/dev/null 2>&1
}

# 检查 app 是否在前台
is_foreground() {
    local resumed
    resumed=$($ADB -s "$DEVICE" shell "dumpsys activity activities | grep mResumedActivity" 2>/dev/null)
    echo "$resumed" | grep -q "$PACKAGE"
}

# 启动 app
launch_app() {
    $ADB -s "$DEVICE" shell "am start -n $ACTIVITY" >/dev/null 2>&1
}

log "Fire TV Watchdog started (device=$DEVICE, interval=${CHECK_INTERVAL}s)"

while true; do
    ensure_connected

    if ! is_foreground; then
        log "App not in foreground, launching..."
        launch_app
        sleep 3
        if is_foreground; then
            log "App restored to foreground"
        else
            log "WARNING: Launch failed, will retry"
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
