package com.ifixforu.dashboard;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

/**
 * 前台守护服务（独立进程）：每 10 秒无条件拉起 MainActivity。
 * API < 29: 直接 startActivity（无后台限制）
 * API >= 29: 用 Runtime am start 绕过限制
 */
public class WatchdogService extends Service {

    private static final String TAG = "WatchdogService";
    private static final long CHECK_INTERVAL_MS = 10_000;
    private static final String CHANNEL_ID = "watchdog_channel";
    private static final int NOTIFICATION_ID = 1;

    private Handler handler;
    private Runnable checker;

    @Override
    public void onCreate() {
        super.onCreate();
        Log.w(TAG, "=== onCreate, API " + Build.VERSION.SDK_INT + " ===");
        createNotificationChannel();
        startForeground(NOTIFICATION_ID, buildNotification());

        handler = new Handler(Looper.getMainLooper());
        checker = new Runnable() {
            @Override
            public void run() {
                launchMainActivity();
                handler.postDelayed(this, CHECK_INTERVAL_MS);
            }
        };
        handler.postDelayed(checker, CHECK_INTERVAL_MS);
        Log.w(TAG, "Checker started");
    }

    private void launchMainActivity() {
        try {
            Intent launch = new Intent(WatchdogService.this, MainActivity.class);
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            startActivity(launch);
            Log.w(TAG, "startActivity OK");
        } catch (Exception e) {
            Log.e(TAG, "startActivity failed: " + e.getMessage());
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Dashboard Watchdog",
                    NotificationManager.IMPORTANCE_MIN);
            channel.setShowBadge(false);
            channel.setSound(null, null);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder
                .setContentTitle("Dashboard Running")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setPriority(Notification.PRIORITY_MIN)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (handler != null) handler.removeCallbacks(checker);
        Log.w(TAG, "Service destroyed");
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        Log.w(TAG, "Task removed, restarting service");
        Intent restart = new Intent(this, WatchdogService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(restart);
        } else {
            startService(restart);
        }
    }
}
