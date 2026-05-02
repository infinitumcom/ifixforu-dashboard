package com.ifixforu.dashboard;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

public class MainActivity extends Activity {

    private static final String DASHBOARD_URL = "http://10.0.0.12:9999";
    private static final long RELOAD_INTERVAL_MS = 5 * 60 * 1000;

    private WebView webView;
    private TextView errorView;
    private Handler handler;
    private Runnable reloadRunnable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        hideSystemUI();

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0a1628"));

        errorView = new TextView(this);
        errorView.setTextColor(Color.WHITE);
        errorView.setTextSize(20);
        errorView.setBackgroundColor(Color.parseColor("#0a1628"));
        errorView.setPadding(80, 80, 80, 80);
        errorView.setVisibility(View.GONE);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#0a1628"));

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                errorView.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);
                injectHelperScripts(view);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showError("Cannot connect\n\n" + DASHBOARD_URL + "\n\nRetrying in 10s...");
                    handler.postDelayed(() -> webView.loadUrl(DASHBOARD_URL), 10000);
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient());

        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(errorView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        setContentView(root);
        webView.loadUrl(DASHBOARD_URL);

        handler = new Handler(Looper.getMainLooper());
        reloadRunnable = () -> {
            webView.reload();
            handler.postDelayed(reloadRunnable, RELOAD_INTERVAL_MS);
        };
        handler.postDelayed(reloadRunnable, RELOAD_INTERVAL_MS);
    }

    private void injectHelperScripts(WebView view) {
        // Inject JS to merge live items/notices from API into dashboard
        String js = "(function() {" +
            "if (typeof window._origLoadData === 'undefined' && typeof window.loadData === 'function') {" +
            "  window._origLoadData = window.loadData;" +
            "  window.loadData = async function() {" +
            "    var result = await window._origLoadData();" +
            "    try {" +
            "      if (result && result.items && result.items.length > 0) {" +
            "        if (typeof MOCK_DATA !== 'undefined') MOCK_DATA.items = result.items;" +
            "      }" +
            "      if (result && result.notices && result.notices.length > 0) {" +
            "        if (typeof MOCK_DATA !== 'undefined') MOCK_DATA.notices = result.notices;" +
            "      }" +
            "    } catch(e) { console.log('merge error', e); }" +
            "    return result;" +
            "  };" +
            "}" +
            "})();";
        view.evaluateJavascript(js, null);
    }

    private void showError(String message) {
        errorView.setText(message);
        errorView.setVisibility(View.VISIBLE);
    }

    private void hideSystemUI() {
        View decorView = getWindow().getDecorView();
        decorView.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER) {
            webView.reload();
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MENU) {
            webView.reload();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUI();
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUI();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (handler != null) handler.removeCallbacks(reloadRunnable);
        if (webView != null) webView.destroy();
    }
}
