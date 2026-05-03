package com.ifixforu.dashboard;

import android.app.Activity;
import android.content.Intent;
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

    private static final String DASHBOARD_URL = "http://64.62.248.68:8889";
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
        webView.setVisibility(View.INVISIBLE);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUseWideViewPort(false);
        settings.setLoadWithOverviewMode(false);
        settings.setMediaPlaybackRequiresUserGesture(false);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                errorView.setVisibility(View.GONE);
                injectHelperScripts(view);
                // 延迟显示，等注入完成后再展示，避免横竖屏闪烁
                handler.postDelayed(() -> webView.setVisibility(View.VISIBLE), 800);
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

        // 启动守护服务
        startService(new Intent(this, WatchdogService.class));
    }

    @Override
    public void onBackPressed() {
        // 屏蔽返回键，防止误退出
    }

    /**
     * 注入 CSS/JS 修正竖屏布局 + 修复 API 连接 + 过滤门店
     * 所有修改通过注入实现，不修改服务器端代码
     */
    private void injectHelperScripts(WebView view) {
        String script =
            "(function() {" +
            "  if (typeof CONFIG !== 'undefined') { CONFIG.API_BASE = 'http://64.62.248.68:8889'; CONFIG.REFRESH_INTERVAL = 5000; }" +
            "  if (typeof MOCK_DATA !== 'undefined') { MOCK_DATA.reviews = MOCK_DATA.reviews || {}; MOCK_DATA.reviews.wechat = { total: 6145 }; MOCK_DATA.items = []; MOCK_DATA.notices = []; }" +

            // 2. CSS overrides
            "  var old = document.getElementById('ifixforu-apk-overrides');" +
            "  if (old) old.remove();" +
            "  var css = document.createElement('style');" +
            "  css.id = 'ifixforu-apk-overrides';" +
            "  css.innerHTML = [" +
            "    '*, *::before, *::after { cursor: none !important; }'," +
            "    '#app { animation: none !important; }'," +
            "    '#app {'," +
            "    '  grid-template-rows:'," +
            "    '    80px'," +
            "    '    54px'," +
            "    '    46px'," +
            "    '    240px'," +
            "    '    1fr'," +
            "    '    115px'," +
            "    '    108px'," +
            "    '    270px'," +
            "    '    18px'," +
            "    '  !important;'," +
            "    '}'," +
            "    '.header { padding: 8px 18px !important; gap: 10px !important; }'," +
            "    '.store-name { font-size: 28px !important; }'," +
            "    '.header-clock { font-size: 42px !important; }'," +
            "    '.header-date { font-size: 12px !important; }'," +
            "    '.shift-bar { padding: 6px 16px !important; gap: 10px !important; }'," +
            "    '.shift-label { font-size: 13px !important; padding: 4px 10px !important; }'," +
            "    '.shift-emp-name { font-size: 14px !important; }'," +
            "    '.shift-emp-avatar { width: 24px !important; height: 24px !important; font-size: 11px !important; }'," +
            "    '.notice-strip { padding: 6px 14px !important; gap: 8px !important; }'," +
            "    '.notice-strip-label { font-size: 12px !important; padding: 3px 8px !important; }'," +
            "    '.stats-row { overflow: visible !important; }'," +
            "    '.pipeline-card { overflow: visible !important; }'," +
            "    '.rankings-fixed.bar-mode { padding: 6px 18px !important; gap: 1px !important; overflow: hidden !important; }'," +
            "    '.rank-bar-item { padding: 0 !important; }'," +
            "    '.rank-bar-track { height: 12px !important; }'," +
            "    '.rank-bar-name { font-size: 13px !important; }'," +
            "    '.rank-bar-amount { font-size: 14px !important; }'," +
            "    '.rank-fixed-pos { font-size: 18px !important; min-width: 20px !important; }'," +
            "    '.item-text { font-size: 21px !important; line-height: 1.3 !important; }'," +
            "    '.item-meta { font-size: 15px !important; }'," +
            "    '.item-emoji { font-size: 28px !important; }'," +
            "    '.item-id { font-size: 15px !important; }'," +
            "    '.meta-chip { font-size: 14px !important; }'," +
            "    '.board-title { font-size: 18px !important; }'," +
            "    '.board-badge { font-size: 14px !important; }'," +
            "    '.status-bar { padding: 1px 16px !important; font-size: 10px !important; gap: 6px !important; min-height: 0 !important; height: 18px !important; }'," +
            "    '.footer-stat-dot { width: 6px !important; height: 6px !important; }'," +
            "    '.pipeline-card { padding: 8px 10px !important; }'," +
            "    '.pipeline-title { font-size: 14px !important; margin-bottom: 2px !important; }'," +
            "    '.pipeline-stages { display: flex !important; flex-direction: column !important; gap: 2px !important; }'," +
            "    '.pipeline-stage { flex-direction: row !important; gap: 6px !important; align-items: center !important; padding: 3px 8px !important; }'," +
            "    '.pipeline-stage-icon { font-size: 14px !important; }'," +
            "    '.pipeline-stage-label { font-size: 12px !important; }'," +
            "    '.pipeline-stage-count { font-size: 22px !important; margin-left: auto !important; }'," +
            "    '.pipeline-total { font-size: 13px !important; padding-top: 2px !important; margin-top: 2px !important; }'," +
            "    '.recommend-card { padding: 6px 10px !important; overflow: visible !important; }'," +
            "    '.recommend-header { margin-bottom: 4px !important; padding-bottom: 4px !important; }'," +
            "    '.recommend-icon { font-size: 14px !important; }'," +
            "    '.recommend-card-title, .recommend-title { font-size: 13px !important; }'," +
            "    '.recommend-item { padding: 4px 8px !important; }'," +
            "    '.recommend-item-emoji { font-size: 22px !important; }'," +
            "    '.recommend-item-name { font-size: 16px !important; }'," +
            "    '.recommend-item-desc { font-size: 12px !important; }'," +
            "    '.recommend-item-price { font-size: 18px !important; font-weight: 700 !important; }'," +
            "    '.recommend-row { gap: 8px !important; }'," +
            "    '.revenue-cats { grid-template-columns: repeat(5, 1fr) !important; gap: 6px !important; }'," +
            "    '.rev-cat { padding: 2px 4px !important; gap: 3px !important; }'," +
            "    '.rev-cat.other { --cat-color: var(--accent-orange); }'," +
            "    '@keyframes notice-scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }'," +
            "    '.notice-strip-track { animation: notice-scroll 30s linear infinite !important; will-change: transform !important; }'," +
            "    '.notice-strip-content { overflow: hidden !important; white-space: nowrap !important; }'," +
            "    '.review-count { font-size: 42px !important; }'," +
            "    '.review-platform { font-size: 14px !important; letter-spacing: 2px !important; }'," +
            "    '.review-growth { font-size: 17px !important; }'," +
            "    '.review-growth.no-new { font-size: 16px !important; }'," +
            "    '.rv-baseline { font-size: 14px !important; }'" +
            "  ].join('\\n');" +
            "  document.head.appendChild(css);" +

            // 3. Patch render functions after delay
            "  setTimeout(function() {" +
            "    if (typeof renderBoard === 'function' && !renderBoard.__patched) {" +
            "      var _origBoard = renderBoard;" +
            "      renderBoard = function(items) {" +
            "        var sorted = items.slice().sort(function(a,b){ return (b.id||0)-(a.id||0); });" +
            "        var pending = sorted.filter(function(i){ return i.status !== 'done'; });" +
            "        _origBoard(pending.slice(0, 15));" +
            "      };" +
            "      renderBoard.__patched = true; window.renderBoard = renderBoard;" +
            "    }" +
            "    if (typeof renderRecommendations === 'function' && !renderRecommendations.__patched) {" +
            "      var _origRec = renderRecommendations;" +
            "      renderRecommendations = function(d) {" +
            "        var p = Object.assign({}, d);" +
            "        if (p.daily_combos) p.daily_combos = p.daily_combos.slice(0, 1);" +
            "        if (p.accessories) p.accessories = p.accessories.slice(0, 1);" +
            "        _origRec(p);" +
            "      }; renderRecommendations.__patched = true; window.renderRecommendations = renderRecommendations;" +
            "    }" +
            "    if (typeof renderRankingsFixed === 'function' && !renderRankingsFixed.__patched) {" +
            "      var _origRank = renderRankingsFixed;" +
            "      renderRankingsFixed = function(rankings, currentCode) {" +
            "        var filtered = rankings.filter(function(r) { return r.code !== 'alhambra'; });" +
            "        _origRank(filtered, currentCode);" +
            "      }; renderRankingsFixed.__patched = true; window.renderRankingsFixed = renderRankingsFixed;" +
            "    }" +
            "    if (typeof renderShift === 'function' && !renderShift.__patched) {" +
            "      var _origShift = renderShift;" +
            "      renderShift = function(shift) {" +
            "        _origShift(shift);" +
            "        var labelEl = document.querySelector('.shift-label');" +
            "        if (labelEl) { var spans = labelEl.querySelectorAll('span'); if (spans.length >= 2) spans[1].textContent = '\\u4eca\\u65e5\\u5f53\\u73ed\\u5458\\u5de5'; }" +
            "        try {" +
            "          var now = new Date();" +
            "          var pst = new Date(now.toLocaleString('en-US', { timeZone: 'America/Los_Angeles' }));" +
            "          var tom = new Date(pst.getTime() + 86400000);" +
            "          var tomStr = tom.getFullYear() + '-' + String(tom.getMonth()+1).padStart(2,'0') + '-' + String(tom.getDate()).padStart(2,'0');" +
            "          var storeCode = (typeof CONFIG !== 'undefined' && CONFIG.STORE_CODE) ? CONFIG.STORE_CODE : 'san_gabriel';" +
            "          var STORE_MAP = { san_gabriel:'SG', monterey_park:'MPK', arcadia_1:'AR', arcadia_2:'AR3', irvine:'IR', rancho_cucamonga:'RANCHO', las_vegas:'NV', rowland_heights:'RH' };" +
            "          var abbr = STORE_MAP[storeCode] || 'SG';" +
            "          var tomSched = (typeof WEEKLY_SCHEDULE !== 'undefined' && WEEKLY_SCHEDULE[tomStr]) ? WEEKLY_SCHEDULE[tomStr][abbr] : null;" +
            "          var nextEl = document.getElementById('shiftNext');" +
            "          if (nextEl && tomSched) { nextEl.textContent = '\\u660e\\u65e5\\u5f53\\u73ed: ' + tomSched.join(', '); }" +
            "          else if (nextEl) { nextEl.textContent = '\\u660e\\u65e5\\u5f53\\u73ed: \\u672a\\u6392\\u73ed'; }" +
            "          var hoursEl = document.getElementById('shiftHours');" +
            "          if (hoursEl) hoursEl.textContent = shift.hours || '10:00 - 19:00';" +
            "        } catch(e) {}" +
            "      }; renderShift.__patched = true; window.renderShift = renderShift;" +
            "    }" +

            // Revenue category icons + labels
            "    var catMap = { repair: { icon: '\\ud83d\\udee0\\ufe0f', label: '\\u7ef4\\u4fee' }, activation: { icon: '\\ud83d\\udcf2', label: '\\u5f00\\u5361' }, accessory: { icon: '\\ud83d\\udcb0', label: '\\u5145\\u503c' }, sales: { icon: '\\ud83d\\uded2', label: '\\u9500\\u552e' } };" +
            "    Object.keys(catMap).forEach(function(key) {" +
            "      var el = document.querySelector('.rev-cat.' + key);" +
            "      if (!el) return;" +
            "      var iconEl = el.querySelector('.rev-cat-icon');" +
            "      if (iconEl) iconEl.textContent = catMap[key].icon;" +
            "      if (!el.querySelector('.rev-cat-label')) {" +
            "        var lbl = document.createElement('span');" +
            "        lbl.className = 'rev-cat-label';" +
            "        lbl.textContent = catMap[key].label;" +
            "        lbl.style.cssText = 'font-size:11px;color:rgba(255,255,255,0.6);font-family:var(--font-mono);letter-spacing:1px;';" +
            "        el.insertBefore(lbl, iconEl.nextSibling);" +
            "      }" +
            "    });" +

            // Add 5th "其他" category
            "    var catsContainer = document.getElementById('revenueCats');" +
            "    if (catsContainer && !document.getElementById('otherAmt')) {" +
            "      var otherDiv = document.createElement('div');" +
            "      otherDiv.className = 'rev-cat other';" +
            "      otherDiv.innerHTML = '<span class=\"rev-cat-icon\">\\ud83d\\udccb</span>' +" +
            "        '<span class=\"rev-cat-label\" style=\"font-size:11px;color:rgba(255,255,255,0.6);font-family:var(--font-mono);letter-spacing:1px;\">\\u5176\\u4ed6</span>' +" +
            "        '<span class=\"rev-cat-amount\" id=\"otherAmt\">$0</span>' +" +
            "        '<span class=\"rev-cat-pct\" id=\"otherPct\">0%</span>';" +
            "      catsContainer.appendChild(otherDiv);" +
            "    }" +

            // Patch renderRevenue for "其他"
            "    if (typeof renderRevenue === 'function' && !renderRevenue.__patched) {" +
            "      var _origRevenue = renderRevenue;" +
            "      renderRevenue = function(d) {" +
            "        _origRevenue(d);" +
            "        var bd = d.revenue_breakdown || { repair:0, activation:0, accessory:0, sales:0 };" +
            "        var known = (bd.repair||0) + (bd.activation||0) + (bd.accessory||0) + (bd.sales||0);" +
            "        var dailyRev = (d.sales && d.sales.daily_revenue) || 0;" +
            "        var otherAmt = Math.max(0, dailyRev - known);" +
            "        var total = known + otherAmt;" +
            "        var pct = total > 0 ? Math.round((otherAmt / total) * 100) : 0;" +
            "        var amtEl = document.getElementById('otherAmt');" +
            "        var pctEl = document.getElementById('otherPct');" +
            "        if (amtEl) amtEl.textContent = '$' + (typeof formatNumber === 'function' ? formatNumber(otherAmt) : otherAmt);" +
            "        if (pctEl) pctEl.textContent = pct + '%';" +
            "      }; renderRevenue.__patched = true; window.renderRevenue = renderRevenue;" +
            "    }" +

            // Pipeline: 质检 → 主板维修待取
            "    var qcLabel = document.querySelector('.pipeline-stage.qc .pipeline-stage-label');" +
            "    if (qcLabel) qcLabel.textContent = '\\u4e3b\\u677f\\u7ef4\\u4fee\\u5f85\\u53d6';" +

            "    window.dispatchEvent(new Event('resize'));" +
            "    if (typeof loadData === 'function') loadData();" +
            "  }, 500);" +
            "})();";
        view.evaluateJavascript(script, null);
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
