/* ──────────────────────────────────────
   Market Trace V6.0 — Dashboard Logic
   Shared utilities exposed via window.MT6
   Tab renderers extracted to tab-*.js
   ────────────────────────────────────── */

/* ── Shared Utilities & State ── */
(function() {
  'use strict';

  var _TZ_OPTS = { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };

  var UTIL = {
    /* ── Helpers ── */
    escapeHtml: function(str) {
      var div = document.createElement('div');
      div.appendChild(document.createTextNode(str));
      return div.innerHTML;
    },
    $id: function(id) { return document.getElementById(id); },

    fmtTime: function(seconds) {
      var s = Math.floor(seconds), m = Math.floor(s / 60), h = Math.floor(m / 60);
      m %= 60;
      return h ? h + 'h' + m + 'm' : m + 'm' + (s % 60) + 's';
    },

    _ts: function(str) {
      if (!str) return '\u2014';
      try {
        return new Date(str).toLocaleString('zh-CN', _TZ_OPTS);
      } catch(e) {
        return str.substring(0, 19).replace('T', ' ');
      }
    },

    _wcll: function(items, sym) {
      var item = items.find ? items.find(function(w) { return w.symbol === sym; }) : null;
      return item || {};
    },

    /* ── Fetch with timeout & retry ── */
    fetchAuth: function(url, options) {
      options = options || {};
      options.credentials = 'same-origin';
      var timeoutMs = options.timeout != null ? options.timeout : 15000;
      delete options.timeout;
      options.signal = options.signal || AbortSignal.timeout(timeoutMs);
      return UTIL.fetchWithRetry(url, options);
    },

    fetchWithRetry: function(url, options, retries, delay) {
      retries = retries != null ? retries : 3;
      delay = delay != null ? delay : 1000;
      var isPost = options.method === 'POST';
      if (isPost) retries = 0;
      return fetch(url, options).then(function(r) {
        if (r.status === 401 && !UTIL._loginPromptShown) {
          UTIL._loginPromptShown = true;
          UTIL.showToast('未登录：请访问 /login 完成认证', 'error');
        }
        if (!r.ok && retries > 0 && r.status >= 500) {
          return new Promise(function(resolve) {
            setTimeout(function() { resolve(UTIL.fetchWithRetry(url, options, retries - 1, delay * 2)); }, delay);
          });
        }
        return r;
      });
    },

    /* ── Toast ── */
    showToast: function(msg, type) {
      type = type || 'error';
      var existing = document.querySelectorAll('.toast');
      if (existing.length >= 3) { existing[0].remove(); }
      var el = document.createElement('div');
      el.className = 'toast toast-' + type;
      el.setAttribute('role', 'alert');
      el.textContent = msg;
      document.body.appendChild(el);
      setTimeout(function() { el.remove(); }, 5000);
    },

    /* ── Shared Constants ── */
    BTN_DIAGNOSE: '\uD83D\uDD0D 诊股',
    STRATEGY_LABELS: {
      breakout: '强势突破', oversold: '超跌反弹', strength: '主力介入',
      risk: '风险预警', ma_golden_cross: '均线金叉', volume_breakout: '放量突破',
      rsi_reversal: 'RSI反转'
    },
    RISK_ACTION_LABELS: {
      'REDUCE_CONFIDENCE': '降低置信度',
      'FORCE_SELL': '强制卖出',
      'STOP_LOSS': '止损',
      'MAX_DRAWDOWN': '回撤超限',
      'POSITION_LIMIT': '仓位超限',
    },
    SEVERITY_LABELS: {
      'normal': '正常', 'warning': '警告', 'elevated': '关注', 'critical': '危险',
    },
    ACTION_LABELS: {
      'BUY': '买入', 'SELL': '卖出', 'HOLD': '持仓观望', 'WAIT': '等待',
    },
    LLM_TIERS: ['primary', 'secondary', 'tertiary', 'quaternary', 'quinary', 'senary', 'septenary', 'octonary'],
    POLL_INTERVAL: 30000,

    fmtAction: function(a) { return UTIL.ACTION_LABELS[a] || a; },
    fmtRiskLevel: function(l) { return UTIL.SEVERITY_LABELS[l] || l; },

    /* ── Analyze Overlay ── */
    _aoSteps: [
      '正在拉取K线数据...',
      '计算14项技术指标 (RSI/MACD/布林/KDJ/ATR/支撑阻力)...',
      '检测7策略信号 (突破/超跌/主力/金叉/放量/RSI反转)...',
      'AI多模型决策中 (DeepSeek → Gemini → GLM → 千帆)...',
      '生成诊股报告...',
    ],

    _showAnalyzeOverlay: function(symbol, stockName) {
      UTIL.state._aoStepIdx = 0;
      var overlay = document.createElement('div');
      overlay.className = 'analyze-overlay';
      overlay.id = 'analyze-overlay';
      overlay.setAttribute('role', 'status');
      overlay.setAttribute('aria-live', 'polite');
      overlay.innerHTML =
        '<div class="ao-spinner"></div>' +
        '<div class="ao-title">' + UTIL.BTN_DIAGNOSE + ' ' + UTIL.escapeHtml(symbol) + (stockName ? ' ' + UTIL.escapeHtml(stockName) : '') + '</div>' +
        '<div class="ao-step" id="ao-step">' + UTIL._aoSteps[0] + '</div>' +
        '<div class="ao-symbol">预计耗时 15-60 秒，取决于 LLM 响应速度</div>';
      document.body.appendChild(overlay);

      UTIL.state._aoTimer = setInterval(function() {
        UTIL.state._aoStepIdx = (UTIL.state._aoStepIdx + 1) % UTIL._aoSteps.length;
        var el = document.getElementById('ao-step');
        if (el) { el.style.opacity = '0'; setTimeout(function() { el.textContent = UTIL._aoSteps[UTIL.state._aoStepIdx]; el.style.opacity = '1'; }, 400); }
      }, 4000);
    },

    _hideAnalyzeOverlay: function() {
      if (UTIL.state._aoTimer) { clearInterval(UTIL.state._aoTimer); UTIL.state._aoTimer = null; }
      var overlay = document.getElementById('analyze-overlay');
      if (overlay) overlay.remove();
    },

    _showSkeletons: function() {
      var g = document.querySelector('.grid');
      if (!g) return;
      for (var i = 0; i < 5; i++) {
        var sk = document.createElement('div');
        sk.className = 'skeleton-card';
        sk.innerHTML = '<div class="skeleton-line" style="width:40%"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';
        g.appendChild(sk);
      }
    },

    _clearSkeletons: function() {
      var sk = document.querySelectorAll('.skeleton-card');
      sk.forEach(function(s) { s.remove(); });
    },

    /* ── Shared Render Helpers ── */
    _renderDiagBtn: function(symbol) {
      return '<button data-diag="' + UTIL.escapeHtml(symbol) + '" class="strat-btn strat-btn-primary" style="font-size:12px;padding:2px 8px">' + UTIL.BTN_DIAGNOSE + '</button>';
    },

    _renderMarketIndex: function(data) {
      var container = UTIL.$id('market-index-items');
      if (!container) return;
      var indices = data && data.indices ? data.indices : null;
      if (!indices || !indices.length) {
        container.innerHTML = '<div style="color:var(--text-muted);font-size:13px">等待数据...</div>';
        return;
      }
      var html = '<div class="mi-row2 mi-header" style="font-weight:600;color:var(--text-muted);font-size:11px;border-bottom:2px solid var(--border-color);padding-bottom:4px;margin-bottom:2px">';
      html += '<span class="mi-col-name">名称</span>';
      html += '<span class="mi-col-price">最新价</span>';
      html += '<span class="mi-col-chg">涨跌额</span>';
      html += '<span class="mi-col-pct">涨跌幅</span>';
      html += '<span class="mi-col-vol">成交量(手)</span>';
      html += '</div>';
      indices.forEach(function(idx) {
        var name = idx.name || idx.code || '';
        var close = idx.close != null ? idx.close.toFixed(2) : '\u2014';
        var chgAmt = idx.change != null ? (idx.change >= 0 ? '+' : '') + idx.change.toFixed(2) : '\u2014';
        var chgPct = idx['\u6DA8\u8DCC\u5E45'] != null ? idx['\u6DA8\u8DCC\u5E45'] : 0;
        var cls = chgPct >= 0 ? 'trend-up' : 'trend-down';
        var volStr = '\u2014';
        if (idx.volume != null) {
          var v = idx.volume;
          if (v >= 1e8) {
            volStr = (v / 1e8).toFixed(1) + '\u4EBF';
          } else if (v >= 1e4) {
            volStr = (v / 1e4).toFixed(0) + '\u4E07';
          } else {
            volStr = v.toFixed(0);
          }
        }
        html += '<div class="mi-row2">';
        html += '<span class="mi-col-name">' + UTIL.escapeHtml(name) + '</span>';
        html += '<span class="mi-col-price">' + close + '</span>';
        html += '<span class="mi-col-chg ' + cls + '">' + chgAmt + '</span>';
        html += '<span class="mi-col-pct ' + cls + '">' + chgPct.toFixed(2) + '%</span>';
        html += '<span class="mi-col-vol">' + volStr + '</span>';
        html += '</div>';
      });
      var breadth = data && data.breadth;
      if (breadth && (breadth.up || breadth.down)) {
        html += '<div class="mi-breadth">';
        html += '<span style="color:var(--color-rise)">\u2191 ' + (breadth.up || 0) + ' \u5BB6</span>';
        html += '<span style="color:var(--color-fall)">\u2193 ' + (breadth.down || 0) + ' \u5BB6</span>';
        html += '<span style="color:var(--text-muted)">\u2194 ' + (breadth.flat || 0) + ' \u5BB6</span>';
        html += '</div>';
      }
      if (data && data.timestamp) {
        html += '<div class="mi-time">\u66F4\u65B0: ' + UTIL._ts(data.timestamp) + '</div>';
      }
      container.innerHTML = html;
    },

    _renderWatchlistItems: function(items) {
      if (!items || !items.length) {
        return '<div style="color:var(--text-muted);font-size:13px">暂无持仓</div>';
      }
      var html = '';
      items.forEach(function(item, idx) {
        var changeCls = item.change_pct != null ? (item.change_pct >= 0 ? 'trend-up' : 'trend-down') : '';
        var changeStr = item.change_pct != null ? '<span class="' + changeCls + '"><span aria-hidden="true">' + (item.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + item.change_pct.toFixed(2) + '%</span>' : '\u2014';
        var priceStr = item.price != null ? item.price.toFixed(2) : '\u2014';
        var nameStr = item.name || '';
        var displayName = nameStr ? UTIL.escapeHtml(nameStr) + ' <span style="color:var(--text-secondary);font-size:11px">' + UTIL.escapeHtml(item.symbol) + '</span>' : UTIL.escapeHtml(item.symbol);
        html += '<div class="wl-row" draggable="true" data-sym="' + UTIL.escapeHtml(item.symbol) + '" data-idx="' + idx + '" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg-tag);font-size:13px">';
        html += '<span style="display:inline-block;width:18px;cursor:grab;color:var(--text-muted);font-size:14px;flex-shrink:0" title="拖拽排序" aria-hidden="true">&#x2630;</span>';
        html += '<span style="cursor:pointer;flex:1" onclick="window._DS.diag(\'' + UTIL.escapeHtml(item.symbol) + '\')" title="点击诊股">' + displayName + '</span>';
        html += '<span style="margin:0 8px">' + priceStr + '</span>';
        html += '<span style="margin:0 8px;min-width:60px;text-align:right">' + changeStr + '</span>';
        html += '<button onclick="event.stopPropagation();window._DS.rmwl(\'' + UTIL.escapeHtml(item.symbol) + '\')" style="background:none;border:none;color:var(--color-red);cursor:pointer;font-size:16px;padding:0 4px" title="移除" aria-label="移除 ' + UTIL.escapeHtml(item.symbol) + '">\u00D7</button>';
        html += '</div>';
      });
      return html;
    },

    /* ── Watchlist Drag & Drop Sort ── */
    _wlSortOrder: [],

    _loadWlSortOrder: function() {
      try {
        var raw = localStorage.getItem('mt6_wl_order');
        UTIL._wlSortOrder = raw ? JSON.parse(raw) : [];
      } catch(e) { UTIL._wlSortOrder = []; }
    },

    _saveWlSortOrder: function() {
      try {
        localStorage.setItem('mt6_wl_order', JSON.stringify(UTIL._wlSortOrder));
      } catch(e) {}
    },

    _applyWlSortOrder: function(items) {
      if (!UTIL._wlSortOrder.length) return items;
      var map = {};
      items.forEach(function(it) { map[it.symbol] = it; });
      var ordered = [];
      UTIL._wlSortOrder.forEach(function(sym) {
        if (map[sym]) { ordered.push(map[sym]); delete map[sym]; }
      });
      Object.keys(map).forEach(function(sym) { ordered.push(map[sym]); });
      return ordered;
    },

    _updateWlSortOrder: function(items) {
      UTIL._wlSortOrder = items.map(function(it) { return it.symbol; });
      UTIL._saveWlSortOrder();
    },

    /* ── Shared State ── */
    state: {
      _analyzeLoading: false,
      _screenAbort: null,
      _stockNames: {},
      _btDetailSym: null,
      _tabCache: {},
      _activeTab: 'health',
      _countdownSec: 30,
      _aoTimer: null,
      _aoStepIdx: 0,
    },

    /* - These will be set by the main IIFE after load() / loadTab() are defined - */
    load: null,
    loadTab: null,

  };

  window.MT6 = UTIL;
})();
