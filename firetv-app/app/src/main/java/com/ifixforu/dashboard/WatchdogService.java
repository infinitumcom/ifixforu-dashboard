package com.ifixforu.dashboard;

import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.app.ActivityManager;
import android.content.Context;

import java.util.List;

/**
 * 守护服务：每 10 秒检查 MainActivity 是否在前台，
 * 如果不在则自动重新启动。
 */
public class WatchdogService extends Service {

    private static final long CHECK_INTERVAL_MS = 10_000;
    private Handler handler;
    private Runnable checker;

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
        checker = new Runnable() {
            @Override
            public void run() {
                if (!isAppInForeground()) {
                    Intent launch = new Intent(WatchdogService.this, MainActivity.class);
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
                    startActivity(launch);
                }
                handler.postDelayed(this, CHECK_INTERVAL_MS);
            }
        };
        handler.postDelayed(checker, CHECK_INTERVAL_MS);
    }

    private boolean isAppInForeground() {
        ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
        List<ActivityManager.RunningAppProcessInfo> processes = am.getRunningAppProcesses();
        if (processes == null) return false;
        for (ActivityManager.RunningAppProcessInfo proc : processes) {
            if (proc.processName.equals(getPackageName())) {
                return proc.importance == ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND;
            }
        }
        return false;
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
    }
}
