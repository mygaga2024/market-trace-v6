/* ──────────────────────────────────────
   Market Trace V6.0 — Dashboard Logic
   ────────────────────────────────────── */
(function() {
  'use strict';

  /* ── Shared Constants ── */
  var STRATEGY_LABELS = {
    breakout: '强势突破', oversold: '超跌反弹', strength: '主力介入',
    risk: '风险预警', ma_golden_cross: '均线金叉', volume_breakout: '放量突破',
    rsi_reversal: 'RSI反转'
  };
  var RISK_ACTION_LABELS = {
    'REDUCE_CONFIDENCE': '降低置信度',
    'FORCE_SELL': '强制卖出',
    'STOP_LOSS': '止损',
    'MAX_DRAWDOWN': '回撤超限',
    'POSITION_LIMIT': '仓位超限',
  };
  var SEVERITY_LABELS = {
    'normal': '正常', 'warning': '警告', 'elevated': '关注', 'critical': '危险',
  };
  var ACTION_LABELS = {
    'BUY': '买入', 'SELL': '卖出', 'HOLD': '持仓观望', 'WAIT': '等待',
  };
  function fmtAction(a) { return ACTION_LABELS[a] || a; }
  function fmtRiskLevel(l) { return SEVERITY_LABELS[l] || l; }
  var BTN_DIAGNOSE = '\uD83D\uDD0D 诊股';
  var LLM_TIERS = ['primary', 'secondary', 'tertiary', 'quaternary', 'quinary', 'senary', 'septenary', 'octonary'];
  var POLL_INTERVAL = 30000;
  var _countdownSec = Math.floor(POLL_INTERVAL / 1000);
  var TAB_FETCHERS = {
    health:       function() { return fetchAuth('/health/detail').then(function(r) { return r.json(); }); },
    status:       function() { return fetchAuth('/status').then(function(r) { return r.json(); }); },
    reports:      function() { return fetchAuth('/reports/macro?limit=5').then(function(r) { return r.json(); }); },
    signal:       function() { return fetchAuth('/reports/signal?limit=5').then(function(r) { return r.json(); }); },
    trace:        function() { return fetchAuth('/reports/trace?limit=5').then(function(r) { return r.json(); }); },
    decisions:    function() { return fetchAuth('/decisions?limit=10').then(function(r) { return r.json(); }); },
    'risk-history': function() { return fetchAuth('/risk/overrides?limit=20').then(function(r) { return r.json(); }); },
    backtest:     function() {
      return Promise.all([
        fetchAuth('/backtest/summary').then(function(r) { return r.json(); }),
        fetchAuth('/backtest/strategies').then(function(r) { return r.json(); }).catch(function() { return null; })
      ]).then(function(results) { return { summary: results[0], strategies: results[1] }; });
    },
    logs:         function() { return fetchAuth('/logs?lines=100').then(function(r) { return r.json(); }); },
    paper:        function() { return fetchAuth('/paper/account').then(function(r) { return r.json(); }); },
    help:         function() { return Promise.resolve({}); },
  };
  var TAB_RENDERERS = {
    health:       renderHealth,
    status:       renderStatus,
    reports:      function(d) { return renderReportList(d, '宏观报告'); },
    signal:       function(d) { return renderReportList(d, '信号报告'); },
    trace:        function(d) { return renderReportList(d, '资金报告'); },
    decisions:    renderDecisions,
    'risk-history': renderRiskHistory,
    backtest:     renderBacktest,
    logs:         renderLogs,
    paper:        renderPaper,
    help:         renderHelp,
  };

  /* ── State ── */
  var _pollTimer = null;
  var _analyzeLoading = false;
  var _screenAbort = null;
  var _activeTab = 'health';
  var _tabCache = {};
  var _btDetailSym = null;

  /* ── Helpers ── */
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function $id(id) { return document.getElementById(id); }

  function fmtTime(seconds) {
    var s = Math.floor(seconds), m = Math.floor(s / 60), h = Math.floor(m / 60);
    m %= 60;
    return h ? h + 'h' + m + 'm' : m + 'm' + (s % 60) + 's';
  }

  var _TZ_OPTS = { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  function _ts(str) {
    if (!str) return '\u2014';
    try {
      return new Date(str).toLocaleString('zh-CN', _TZ_OPTS);
    } catch(e) {
      return str.substring(0, 19).replace('T', ' ');
    }
  }

  function _wcll(items, sym) {
    var item = items.find ? items.find(function(w) { return w.symbol === sym; }) : null;
    return item || {};
  }

  /* ── Fetch with timeout & retry ── */
  function fetchAuth(url, options) {
    options = options || {};
    options.credentials = 'same-origin';
    var timeoutMs = options.timeout != null ? options.timeout : 15000;
    delete options.timeout;
    options.signal = options.signal || AbortSignal.timeout(timeoutMs);
    return fetchWithRetry(url, options);
  }

  function fetchWithRetry(url, options, retries, delay) {
    retries = retries != null ? retries : 3;
    delay = delay != null ? delay : 1000;
    var isPost = options.method === 'POST';
    if (isPost) retries = 0;  // POST 不重试(有副作用)
    return fetch(url, options).then(function(r) {
      if (!r.ok && retries > 0 && r.status >= 500) {
        return new Promise(function(resolve) {
          setTimeout(function() { resolve(fetchWithRetry(url, options, retries - 1, delay * 2)); }, delay);
        });
      }
      return r;
    });
  }

  /* ── Toast ── */
  function showToast(msg, type) {
    type = type || 'error';
    var existing = document.querySelectorAll('.toast');
    if (existing.length >= 3) { existing[0].remove(); }
    var el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.setAttribute('role', 'alert');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function() { el.remove(); }, 5000);
  }

  /* ── Scroll-to-top Button ── */
  function _initScrollTopBtn() {
    var btn = document.createElement('button');
    btn.className = 'scroll-top-btn';
    btn.setAttribute('aria-label', '回到顶部');
    btn.textContent = '\u2191';
    btn.onclick = function() { window.scrollTo({ top: 0, behavior: 'smooth' }); };
    document.body.appendChild(btn);
    window.addEventListener('scroll', function() {
      btn.classList.toggle('visible', window.scrollY > 400);
    }, { passive: true });
  }

  /* ── Shared Watchlist Render ── */
  function _renderWatchlistItems(items) {
    if (!items || !items.length) {
      return '<div style="color:var(--text-muted);font-size:13px">暂无持仓</div>';
    }
    var html = '';
    items.forEach(function(item, idx) {
      var changeCls = item.change_pct != null ? (item.change_pct >= 0 ? 'trend-up' : 'trend-down') : '';
      var changeStr = item.change_pct != null ? '<span class="' + changeCls + '"><span aria-hidden="true">' + (item.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + item.change_pct.toFixed(2) + '%</span>' : '\u2014';
      var priceStr = item.price != null ? item.price.toFixed(2) : '\u2014';
      var nameStr = item.name || '';
      var displayName = nameStr ? escapeHtml(nameStr) + ' <span style="color:var(--text-secondary);font-size:11px">' + escapeHtml(item.symbol) + '</span>' : escapeHtml(item.symbol);
      html += '<div class="wl-row" draggable="true" data-sym="' + escapeHtml(item.symbol) + '" data-idx="' + idx + '" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg-tag);font-size:13px">';
      html += '<span style="display:inline-block;width:18px;cursor:grab;color:var(--text-muted);font-size:14px;flex-shrink:0" title="拖拽排序" aria-hidden="true">&#x2630;</span>';
      html += '<span style="cursor:pointer;flex:1" onclick="window._DS.diag(\'' + escapeHtml(item.symbol) + '\')" title="点击诊股">' + displayName + '</span>';
      html += '<span style="margin:0 8px">' + priceStr + '</span>';
      html += '<span style="margin:0 8px;min-width:60px;text-align:right">' + changeStr + '</span>';
      html += '<button onclick="event.stopPropagation();window._DS.rmwl(\'' + escapeHtml(item.symbol) + '\')" style="background:none;border:none;color:var(--color-red);cursor:pointer;font-size:16px;padding:0 4px" title="移除" aria-label="移除 ' + escapeHtml(item.symbol) + '">\u00D7</button>';
      html += '</div>';
    });
    return html;
  }

  function _renderMarketIndex(data) {
    var container = $id('market-index-items');
    if (!container) return;
    var indices = data && data.indices ? data.indices : null;
    if (!indices || !indices.length) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:13px">等待数据...</div>';
      return;
    }
    var html = '';
    indices.forEach(function(idx) {
      var name = idx.name || idx.code || '';
      var close = idx.close != null ? idx.close.toFixed(2) : '\u2014';
      var chgAmt = idx.change != null ? (idx.change >= 0 ? '+' : '') + idx.change.toFixed(2) : '\u2014';
      var chgPct = idx['\u6DA8\u8DCC\u5E45'] != null ? idx['\u6DA8\u8DCC\u5E45'] : 0;
      var cls = chgPct >= 0 ? 'trend-up' : 'trend-down';
      var volStr = '\u2014';
      if (idx.volume != null) {
        var v = idx.volume / 10000;
        volStr = (v >= 10000 ? (v / 10000).toFixed(1) + '\u4EBF' : v.toFixed(0)) + '\u4E07';
      }
      html += '<div class="mi-row2">';
      html += '<span class="mi-col-name">' + escapeHtml(name) + '</span>';
      html += '<span class="mi-col-price">' + close + '</span>';
      html += '<span class="mi-col-chg ' + cls + '">' + chgAmt + '</span>';
      html += '<span class="mi-col-pct ' + cls + '">' + chgPct.toFixed(2) + '%</span>';
      html += '<span class="mi-col-vol">' + volStr + '</span>';
      html += '</div>';
    });
    var breadth = data && data.breadth;
    if (breadth && (breadth.up || breadth.down)) {
      html += '<div class="mi-breadth">';
      html += '<span style="color:var(--color-green)">\u2191 ' + (breadth.up || 0) + ' \u5BB6</span>';
      html += '<span style="color:var(--color-red)">\u2193 ' + (breadth.down || 0) + ' \u5BB6</span>';
      html += '<span style="color:var(--text-muted)">\u2194 ' + (breadth.flat || 0) + ' \u5BB6</span>';
      html += '</div>';
    }
    if (data && data.timestamp) {
      html += '<div class="mi-time">\u66F4\u65B0: ' + _ts(data.timestamp) + '</div>';
    }
    container.innerHTML = html;
  }

  function _renderDiagBtn(symbol) {
    return '<button data-diag="' + escapeHtml(symbol) + '" class="strat-btn strat-btn-primary" style="font-size:12px;padding:2px 8px">' + BTN_DIAGNOSE + '</button>';
  }

  /* ── Safe card click-to-tab ── */
  function _safeClick(el, tab) {
    if (el) el.addEventListener('click', function() { switchTab(tab); });
  }
  function _safeCardClick(ariaLabel, tab) {
    var card = document.querySelector('.card[aria-label="' + ariaLabel + '"]');
    if (card) card.addEventListener('click', function() { switchTab(tab); });
  }

  /* ── Watchlist Drag & Drop Sort ── */
  var _wlDragSrc = null;
  var _wlSortOrder = [];

  function _loadWlSortOrder() {
    try {
      var raw = localStorage.getItem('mt6_wl_order');
      _wlSortOrder = raw ? JSON.parse(raw) : [];
    } catch(e) { _wlSortOrder = []; }
  }

  function _saveWlSortOrder() {
    try {
      localStorage.setItem('mt6_wl_order', JSON.stringify(_wlSortOrder));
    } catch(e) {}
  }

  function _applyWlSortOrder(items) {
    if (!_wlSortOrder.length) return items;
    var map = {};
    items.forEach(function(it) { map[it.symbol] = it; });
    var ordered = [];
    _wlSortOrder.forEach(function(sym) {
      if (map[sym]) { ordered.push(map[sym]); delete map[sym]; }
    });
    Object.keys(map).forEach(function(sym) { ordered.push(map[sym]); });
    return ordered;
  }

  function _updateWlSortOrder(items) {
    _wlSortOrder = items.map(function(it) { return it.symbol; });
    _saveWlSortOrder();
  }

  function _initWlDragDrop() {
    var container = $id('watchlist-items');
    if (!container) return;

    container.addEventListener('dragstart', function(e) {
      var row = e.target.closest('.wl-row');
      if (!row || !row.draggable) return;
      _wlDragSrc = row;
      row.style.opacity = '0.4';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', row.getAttribute('data-sym'));
    });

    container.addEventListener('dragend', function(e) {
      var row = e.target.closest('.wl-row');
      if (row) row.style.opacity = '1';
      _wlDragSrc = null;
    });

    container.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      var row = e.target.closest('.wl-row');
      if (row && row !== _wlDragSrc) {
        row.style.borderTop = '2px solid var(--accent-blue)';
      }
    });

    container.addEventListener('dragleave', function(e) {
      var row = e.target.closest('.wl-row');
      if (row) row.style.borderTop = '';
    });

    container.addEventListener('drop', function(e) {
      e.preventDefault();
      var target = e.target.closest('.wl-row');
      if (!target || target === _wlDragSrc || !_wlDragSrc) return;
      target.style.borderTop = '';

      var srcSym = _wlDragSrc.getAttribute('data-sym');
      var tgtSym = target.getAttribute('data-sym');

      var newOrder = [];
      var rows = container.querySelectorAll('.wl-row');
      rows.forEach(function(r) { newOrder.push(r.getAttribute('data-sym')); });

      var srcIdx = newOrder.indexOf(srcSym);
      var tgtIdx = newOrder.indexOf(tgtSym);
      if (srcIdx >= 0 && tgtIdx >= 0) {
        newOrder.splice(srcIdx, 1);
        newOrder.splice(tgtIdx, 0, srcSym);
        _wlSortOrder = newOrder;
        _saveWlSortOrder();
        load(); // re-render with new order
      }
    });
  }

  /* ── Analyze Overlay ── */
  var _stockNames = {};
  var _aoSteps = [
    '正在拉取K线数据...',
    '计算14项技术指标 (RSI/MACD/布林/KDJ/ATR/支撑阻力)...',
    '检测7策略信号 (突破/超跌/主力/金叉/放量/RSI反转)...',
    'AI多模型决策中 (DeepSeek → Gemini → GLM → 千帆)...',
    '生成诊股报告...',
  ];
  var _aoTimer = null;
  var _aoStepIdx = 0;

  function _showAnalyzeOverlay(symbol, stockName) {
    _aoStepIdx = 0;
    var overlay = document.createElement('div');
    overlay.className = 'analyze-overlay';
    overlay.id = 'analyze-overlay';
    overlay.setAttribute('role', 'status');
    overlay.setAttribute('aria-live', 'polite');
    overlay.innerHTML =
      '<div class="ao-spinner"></div>' +
      '<div class="ao-title">' + BTN_DIAGNOSE + ' ' + escapeHtml(symbol) + (stockName ? ' ' + escapeHtml(stockName) : '') + '</div>' +
      '<div class="ao-step" id="ao-step">' + _aoSteps[0] + '</div>' +
      '<div class="ao-symbol">预计耗时 15-60 秒，取决于 LLM 响应速度</div>';
    document.body.appendChild(overlay);

    _aoTimer = setInterval(function() {
      _aoStepIdx = (_aoStepIdx + 1) % _aoSteps.length;
      var el = document.getElementById('ao-step');
      if (el) { el.style.opacity = '0'; setTimeout(function() { el.textContent = _aoSteps[_aoStepIdx]; el.style.opacity = '1'; }, 400); }
    }, 4000);
  }

  function _hideAnalyzeOverlay() {
    if (_aoTimer) { clearInterval(_aoTimer); _aoTimer = null; }
    var overlay = document.getElementById('analyze-overlay');
    if (overlay) overlay.remove();
  }
  function _showSkeletons() {
    var g = document.querySelector('.grid');
    if (!g) return;
    for (var i = 0; i < 5; i++) {
      var sk = document.createElement('div');
      sk.className = 'skeleton-card';
      sk.innerHTML = '<div class="skeleton-line" style="width:40%"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';
      g.appendChild(sk);
    }
  }

  async function load() {
    try {
      var results = await Promise.all([
        fetchAuth('/health/detail').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/status').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/reports/macro/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/reports/signal/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/reports/trace/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/risk/status').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/watchlist').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetchAuth('/api/market/index').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      ]);

      var h = results[0], st = results[1], mr = results[2], lr = results[3], dr = results[4], rk = results[5], wl = results[6], mi = results[7];

      _clearSkeletons();

      if (!h) return;

      var ok = h.status === 'ok';
      $id('sys-status').className = 'badge ' + (ok ? 'badge-ok' : 'badge-warn');
      $id('sys-status').innerHTML = '<span aria-hidden="true">' + (ok ? '\u25CF' : '\u25D0') + '</span> ' + (ok ? '正常' : '降级');
      $id('uptime').textContent = fmtTime(h.uptime_seconds);
      // Dynamic footer version
      var fv = document.getElementById('footer-version');
      if (fv && h.version) fv.textContent = h.version;

      if (h.agents) {
        var dots = document.querySelectorAll('.agent-dot .dot');
        var names = ['macro', 'signal', 'trace', 'risk', 'chief'];
        var alive = names.filter(function(n) { return h.agents[n]; }).length;
        $id('agent-count').textContent = alive + '/5';
        names.forEach(function(n, i) {
          if (dots[i]) dots[i].className = 'dot ' + (h.agents[n] ? 'dot-on' : 'dot-off');
        });
      }

      var llmHtml = '';
      if (h.llm_chain) {
        LLM_TIERS.forEach(function(t) {
          var p = h.llm_chain[t];
          if (!p) return;
          var icon = p.api_key_configured ? '\u2713' : '\u2717';
          var cls = p.api_key_configured ? 'llm-status-on' : 'llm-status-off';
          llmHtml += '<div class="llm-row"><span class="llm-name ' + cls + '">' + icon + ' ' + escapeHtml(p.provider) + '</span><span style="font-size:12px;color:var(--text-secondary)">' + escapeHtml(p.model) + '</span></div>';
        });
      }
      $id('llm-chain').innerHTML = llmHtml || '未配置';

      if (rk) {
        var riskLevel = rk.level || 'normal';
        var levelLabels = { normal: '正常', elevated: '关注', critical: '危险' };
        var levelCls = 'risk-' + riskLevel;
        $id('risk-level-display').innerHTML = '<span class="risk-indicator ' + levelCls + '">' + (levelLabels[riskLevel] || riskLevel) + '</span>';
        $id('risk-override-count').textContent = rk.daily_overrides || 0;
        $id('risk-event-count').textContent = rk.total_overrides || 0;
      } else {
        $id('risk-level-display').innerHTML = '<span class="risk-indicator risk-loading">无数据</span>';
        $id('risk-override-count').textContent = '\u2014';
        $id('risk-event-count').textContent = '\u2014';
      }

      $id('watchlist-items').innerHTML = wl && wl.items ? _renderWatchlistItems(_applyWlSortOrder(wl.items)) : '<div style="color:var(--text-muted);font-size:13px">加载中...</div>';
      if (wl && wl.items) {
        wl.items.forEach(function(it) { if (it.name) _stockNames[it.symbol] = it.name; });
      }

      _renderMarketIndex(mi);

      if (mr && mr.data && mr.data.risk_appetite_index != null) {
        var rai = mr.data.risk_appetite_index;
        var interp = mr.data.interpretation || {};
        var cls = rai >= 0.55 ? 'rai-good' : rai >= 0.45 ? 'rai-warm' : 'rai-bad';
        var pct = (rai * 100).toFixed(0);
        $id('rai-value').textContent = rai.toFixed(2);
        $id('rai-value').className = 'rai-value ' + cls;
        $id('rai-label').textContent = interp.regime || '';
        var bar = $id('rai-bar');
        bar.style.width = pct + '%';
        bar.style.background = rai >= 0.55 ? 'var(--color-green)' : rai >= 0.45 ? 'var(--color-yellow)' : 'var(--color-red)';
      } else {
        $id('rai-value').textContent = '\u2014';
        $id('rai-label').textContent = '等待数据';
      }

      var dec = st && st.latest_decision;
      if (dec) {
        var area = $id('decision-area');
        area.style.display = 'block';
        $id('decision-action').innerHTML = '<span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(fmtAction(dec.action)) + '</span>';
        $id('decision-conf').textContent = (dec.confidence * 100).toFixed(0) + '%';
        $id('decision-reason').textContent = dec.reasoning || '';
        $id('decision-provider').textContent = dec.provider || '\u2014';
      }
    } catch (e) {
      console.error(e);
      _clearSkeletons();
    }
  }

  function _clearSkeletons() {
    var sk = document.querySelectorAll('.skeleton-card');
    sk.forEach(function(s) { s.remove(); });
  }

  /* ── Analyze Stock ── */
  function analyzeStock() {
    if (_analyzeLoading) return;
    _analyzeLoading = true;

    var btn = $id('analyze-btn');
    btn.disabled = true;
    btn.textContent = '\u23F3 分析中...';

    var sym = $id('stock-input').value.trim();
    if (!sym) {
      showToast('请输入股票代码', 'warning');
      _analyzeLoading = false;
      btn.disabled = false;
      btn.textContent = BTN_DIAGNOSE;
      return;
    }

    $id('analyze-spinner').style.display = 'none'; // keep old spinner hidden
    $id('analyze-result').style.display = 'none';
    _showAnalyzeOverlay(sym, _stockNames[sym] || '');

    fetchAuth('/analyze/' + sym, { method: 'POST', timeout: 90000 })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var html;
        if (d.error) {
          html = '<div class="error-banner" role="alert"><span aria-hidden="true">\u274C</span> ' + escapeHtml(d.error) + '</div>';
        } else {
          if (d.name) _stockNames[sym] = d.name;
          var dec = d.decision;
          var ind = d.indicators;
          var trend = d.trend || 'sideways';
          var trendLabel = trend === 'bullish' ? '多头排列' : trend === 'bearish' ? '空头排列' : '震荡';

          html = '<div class="result-card">';
          html += '<div style="font-size:18px;font-weight:700;margin-bottom:8px">';
          if (d.name) html += escapeHtml(d.name) + ' ';
          html += '<span style="color:var(--text-secondary);font-size:14px">' + escapeHtml(d.symbol) + '</span>';
          html += '<span style="font-size:12px;color:var(--text-muted);margin-left:8px">' + escapeHtml(trendLabel) + '</span>';
          html += '</div>';
          html += '<div class="result-stats">';
          html += '<div class="result-stat"><div>价格</div><div>' + (d.price != null ? d.price.toFixed(2) : '\u2014') + '</div></div>';
          html += '<div class="result-stat"><div>涨跌</div><div class="' + (d.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (d.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + (d.change_pct != null ? d.change_pct.toFixed(2) : '\u2014') + '%</div></div>';
          html += '<div class="result-stat"><div>RSI</div><div>' + (ind.rsi || '\u2014') + '</div></div>';
          html += '<div class="result-stat"><div>量比</div><div>' + (ind.vol_ratio || 0) + 'x</div></div>';
          html += '<div class="result-stat"><div>ATR</div><div>' + (ind.atr ? ind.atr.toFixed(2) : '\u2014') + '</div></div>';
          html += '</div>';

          html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">';
          html += 'MA5: <strong>' + (ind.ma5 || '-') + '</strong> | MA20: <strong>' + (ind.ma20 || '-') + '</strong>';
          if (ind.ma60) html += ' | MA60: <strong>' + ind.ma60 + '</strong>';
          html += '</div>';

          if (ind.macd && ind.macd.dif) {
            html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">MACD: DIF=' + ind.macd.dif + ' DEA=' + ind.macd.dea + ' BAR=' + ind.macd.histogram + '</div>';
          }
          if (ind.bollinger && ind.bollinger.upper) {
            html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">布林: ' + ind.bollinger.upper + ' / ' + ind.bollinger.middle + ' / ' + ind.bollinger.lower + ' (带宽' + ind.bollinger.bandwidth + ')</div>';
          }
          if (ind.kdj) {
            html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">KDJ: K=' + ind.kdj.k + ' D=' + ind.kdj.d + ' J=' + ind.kdj.j + '</div>';
          }
          if (ind.support_resistance) {
            var sr = ind.support_resistance;
            html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">支撑: <strong style="color:var(--color-green)">' + sr.support + '</strong> | 阻力: <strong style="color:var(--color-red)">' + sr.resistance + '</strong> | 枢轴: ' + sr.pivot + '</div>';
          }

          if (d.strategy_hits && d.strategy_hits.length) {
            html += '<div style="font-size:12px;margin-top:4px"><span aria-hidden="true">\uD83C\uDFAF</span> 策略命中: ';
            html += d.strategy_hits.map(function(s) {
              return '<span class="' + (s.type === 'BUY' ? 'trend-up' : 'trend-down') + '" style="margin-right:6px">' + escapeHtml(s.label) + '</span>';
            }).join('');
            html += '</div>';
          }

          if (d.trace_signals && d.trace_signals.length) {
            html += '<div style="font-size:12px;margin-top:4px"><span aria-hidden="true">\uD83D\uDCCA</span> ';
            html += d.trace_signals.map(function(s) {
              return '<span class="' + (s.direction === 'bullish' ? 'trend-up' : 'trend-down') + '" style="margin-right:6px">' + (s.direction === 'bullish' ? '\u2191' : '\u2193') + ' ' + escapeHtml(s.type) + '</span>';
            }).join(' ');
            html += '</div>';
          }
          if (dec) {
            var status = dec.provider_status || '';
            var isDegraded = status === 'degraded' || status === 'fallback' || status === 'FALLBACK' || status === 'DEGRADED';
            if (isDegraded) {
              var warnCls = status === 'fallback' || status === 'FALLBACK' ? 'toast-error' : 'toast-warning';
              var warnIcon = status === 'fallback' || status === 'FALLBACK' ? '\u274C' : '\u26A0\uFE0F';
              var warnText = status === 'fallback' || status === 'FALLBACK' ? 'LLM链路全部不可用, 已降级到兜底规则' : 'LLM链路降级, 部分模型不可用';
              html += '<div style="margin-top:8px;padding:8px 12px;border-radius:6px;font-size:12px;background:var(--bg-red-subtle);border:1px solid var(--color-red);color:var(--color-red)">';
              html += warnIcon + ' <strong>' + escapeHtml(warnText) + '</strong></div>';
            }
            html += '<div style="margin-top:12px;padding:12px;background:var(--bg-primary);border-radius:8px">';
            html += '<span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(fmtAction(dec.action)) + '</span>';
            html += ' <span style="font-size:13px">置信度 ' + (dec.confidence * 100).toFixed(0) + '%</span>';
            html += '<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(dec.reasoning) + '</div>';
            html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px">AI: ' + escapeHtml(dec.provider) + ' | RAI宏观: ' + d.macro_rai.toFixed(2) + '</div>';
            if (d.data_timestamp) {
              var isLive = d.data_source === 'akshare' && d.data_timestamp.indexOf(new Date().toISOString().substring(0, 10)) >= 0;
              html += '<div style="font-size:10px;color:var(--text-muted);margin-top:2px">\uD83D\uDCC5 数据: ' + escapeHtml(_ts(d.data_timestamp)) + (isLive ? ' <span style="color:var(--color-green)">(\u5B9E\u65F6)</span>' : '') + '</div>';
            }
            html += '</div>';
          }
          html += '</div>';
        }
        $id('analyze-result').innerHTML = html;
        $id('analyze-result').style.display = 'block';
        $id('analyze-result').scrollIntoView({ behavior: 'smooth', block: 'start' });

        if (!d.error) {
          $id('kline-chart').classList.remove('chart-container--hidden');
          fetchAuth('/api/kline/' + sym)
            .then(function(r) { return r.json(); })
            .then(function(kd) { Charts.renderKline('kline-chart', kd); })
            .catch(function() { $id('kline-chart').classList.add('chart-container--hidden'); Charts.destroy('kline-chart'); });

          fetchAuth('/risk/position/' + sym + '?price=' + (d.price || 0))
            .then(function(r) { return r.json(); })
            .then(function(pos) {
              if (pos && !pos.error && $id('analyze-result').style.display !== 'none') {
                var levelCls = 'pos-level-' + (pos.risk_level || 'normal');
                var box = document.createElement('div');
                box.className = 'position-box';
                box.innerHTML = '<div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">\uD83D\uDCC8 仓位建议</div>' +
                  '<span class="pos-level ' + levelCls + '">风控等级: ' + escapeHtml(fmtRiskLevel(pos.risk_level || 'normal')) + '</span> ' +
                  '<span style="color:var(--text-muted)">|</span> ' +
                  '建议: <strong>' + (pos.position_shares || 0) + '</strong> 股 (' +
                  '<strong>' + (pos.suggested_amount || 0).toLocaleString() + '</strong> 元)' +
                  '<div style="margin-top:4px;font-size:11px;color:var(--text-muted)">' +
                  '风险权重: ' + (pos.risk_multiplier || 1).toFixed(2) + 'x | ' +
                  '方法: ' + escapeHtml(pos.method || 'kelly') +
                  '</div>';
                $id('analyze-result').appendChild(box);
              }
            })
            .catch(function() {});
        } else {
          $id('kline-chart').classList.add('chart-container--hidden');
          Charts.destroy('kline-chart');
          $id('analyze-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      })
      .catch(function(e) {
        $id('analyze-result').innerHTML = '<div class="error-banner" role="alert">请求失败: ' + escapeHtml(e.message) + '</div>';
        $id('analyze-result').style.display = 'block';
        $id('analyze-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
      })
      .finally(function() {
        _hideAnalyzeOverlay();
        _analyzeLoading = false;
        btn.disabled = false;
        btn.textContent = BTN_DIAGNOSE;
      });
  }

  /* ── Screen Stocks ── */
  async function screenStocks(strategy) {
    if (_screenAbort) _screenAbort.abort();
    _screenAbort = new AbortController();

    var container = $id('screen-results');
    container.style.display = 'block';
    container.innerHTML = '<div class="spinner" role="status">\u23F3 扫描中...</div>';

    try {
      var r = await fetchAuth('/screen/' + strategy, { method: 'POST', signal: _screenAbort.signal });
      var d = await r.json();
      _screenAbort = null;
      if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }
      renderScreenResults(container, d);
    } catch (e) {
      if (e.name === 'AbortError') return;
      _screenAbort = null;
      container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(e.message) + '</div>';
    }
  }

  function renderScreenResults(container, d) {
    var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px"><span aria-hidden="true">\uD83D\uDCCB</span> ' + escapeHtml(d.strategy) + ' — 匹配 ' + d.matched + ' 只</div>';
    if (d.matched === 0) {
      html += '<div class="tab-empty">暂无匹配的股票</div>';
      html += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);line-height:1.6">策略筛选需缓存的K线数据(&ge;20条)。如果缓存未就绪，将使用实时行情粗筛。可以等待系统预热(约30秒)后重试，或通过<strong>诊股</strong>主动拉取数据填充缓存。</div>';
      container.innerHTML = html;
      return;
    }
    d.results.forEach(function(s) {
      var nameDisplay = s.name ? escapeHtml(s.name) + ' ' : '';
      var price = s.price != null ? s.price.toFixed(2) : '\u2014';
      var chg = s.change_pct != null ? s.change_pct : 0;
      var vr = s.vol_ratio != null ? s.vol_ratio.toFixed(1) : '0.0';
      html += '<div class="strat-result" tabindex="0" data-diag="' + escapeHtml(s.symbol) + '"><span class="price">' + nameDisplay + escapeHtml(s.symbol) + '</span> ' + price + ' <span class="' + (chg >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (chg >= 0 ? '\u2191' : '\u2193') + '</span> ' + chg.toFixed(2) + '%</span> <span style="color:var(--text-secondary)">量比 ' + vr + 'x</span></div>';
    });
    container.innerHTML = html;
  }

  /* ── Full Scan ── */
  function fullScan(strategy) {
    var container = $id('fullscan-results');
    container.style.display = 'block';
    container.innerHTML = '<div class="spinner" role="status">\u23F3 全市场扫描中... 正在扫描5000+只A股，预计30-60秒</div>';

    fetchAuth('/scan/' + strategy, { method: 'POST', timeout: 90000 })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }
        container.innerHTML = _renderScanTable(d);
      })
      .catch(function(e) {
        container.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F ' + escapeHtml(e.message) + '</div>';
      });
  }

  function smartScan() {
    var container = $id('fullscan-results');
    container.style.display = 'block';
    container.innerHTML = '<div class="spinner" role="status">\u23F3 智能扫描中... 7策略×5000+只A股，预计60-90秒</div>';

    fetchAuth('/scan/smart', { method: 'POST', timeout: 90000 })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }
        var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">';
        html += '\uD83E\uDDE0 智能综合扫描 — 全市场7策略评分';
        html += ' | 总计' + d.total + '只 | 命中' + d.scored + '只 | 耗时' + d.elapsed_seconds + 's';
        html += '</div>';
        if (d.results && d.results.length) {
          html += '<table class="tab-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>最优策略</th><th>评分</th><th>操作</th></tr></thead><tbody>';
          d.results.forEach(function(s) {
            var cls = (s.change_pct || 0) >= 0 ? 'trend-up' : 'trend-down';
            html += '<tr><td>' + escapeHtml(s.symbol) + '</td><td>' + escapeHtml(s.name || '') + '</td><td>' + (s.price != null ? s.price.toFixed(2) : '\u2014') + '</td><td class="' + cls + '">' + ((s.change_pct || 0) > 0 ? '+' : '') + (s.change_pct || 0).toFixed(2) + '%</td>';
            html += '<td>' + escapeHtml(s.strategy_label || s.strategy) + '</td><td><strong>' + (s.score || 0).toFixed(1) + '</strong></td>';
            html += '<td>' + _renderDiagBtn(s.symbol) + '</td></tr>';
          });
          html += '</tbody></table>';
        } else {
          html += '<div class="tab-empty">未命中任何股票</div>';
          html += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);line-height:1.6">智能综合扫描需要缓存的K线数据(&ge;30条)进行7策略评分。如果系统刚启动，请等待prefetch预热或手动诊股几只看好的股票来填充缓存。</div>';
        }
        container.innerHTML = html;
      })
      .catch(function(e) {
        container.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F ' + escapeHtml(e.message) + '</div>';
      });
  }

  function _renderScanTable(d) {
    var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">';
    html += '\uD83D\uDD0D ' + escapeHtml(d.strategy) + ' — 全市场扫描';
    html += ' | 总计' + d.total_stocks + '只 | 检查' + d.checked + '只 | 命中<strong>' + d.matched + '</strong>只';
    html += ' | 耗时' + d.elapsed_seconds + 's';
    html += '</div>';
    if (d.results && d.results.length) {
      html += '<table class="tab-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>量比</th><th>操作</th></tr></thead><tbody>';
      d.results.forEach(function(s) {
        var cls = (s.change_pct || 0) >= 0 ? 'trend-up' : 'trend-down';
        html += '<tr><td>' + escapeHtml(s.symbol) + '</td><td>' + escapeHtml(s.name || '') + '</td><td>' + (s.price != null ? s.price.toFixed(2) : '\u2014') + '</td><td class="' + cls + '">' + ((s.change_pct || 0) > 0 ? '+' : '') + (s.change_pct || 0).toFixed(2) + '%</td><td>' + (s.vol_ratio || 0).toFixed(1) + 'x</td>';
        html += '<td>' + _renderDiagBtn(s.symbol) + '</td></tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div class="tab-empty">未命中任何股票</div>';
      html += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);line-height:1.6">全市场扫描依赖缓存的K线数据(&ge;20条)进行深度策略验证。如果系统刚启动，请等待prefetch预热完成(约30-60秒)后重试。</div>';
    }
    return html;
  }

  /* ── Tab Switching ── */
  function switchTab(tab) {
    _activeTab = tab;
    var buttons = document.querySelectorAll('.tab-btn');
    buttons.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
      b.setAttribute('aria-selected', b.getAttribute('data-tab') === tab ? 'true' : 'false');
    });
    var toolbarButtons = document.querySelectorAll('.toolbar-btn');
    toolbarButtons.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    var bc = $id('backtest-chart');
    if (bc) bc.style.display = (tab === 'backtest') ? 'block' : 'none';
    loadTab(tab);
  }

  function refreshActiveTab() {
    delete _tabCache[_activeTab];
    loadTab(_activeTab);
  }

  function loadTab(tab) {
    var panel = $id('tab-panel');
    panel.innerHTML = '<div class="spinner">\u23F3 加载中...</div>';

    var entry = _tabCache[tab];
    if (entry && entry.html && Date.now() - entry.ts < 120000) {
      panel.innerHTML = entry.html;
      return;
    }

    var fn = TAB_FETCHERS[tab];
    if (!fn) { panel.innerHTML = '<div class="tab-empty">未知面板</div>'; return; }

    fn().then(function(data) {
      var renderer = TAB_RENDERERS[tab];
      var html = renderer ? renderer(data) : '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
      _tabCache[tab] = { html: html, ts: Date.now() };
      panel.innerHTML = html;
    }).catch(function(e) {
      panel.innerHTML = '<div class="tab-empty">\u26A0\uFE0F 加载失败: ' + escapeHtml(e.message || '网络错误') + '</div>';
    });
  }

  /* ── Tab Renderers ── */
  function renderHealth(d) {
    var html = '<table class="tab-table"><tbody>';
    html += '<tr><th>系统状态</th><td class="' + (d.status === 'ok' ? 'kv-ok' : 'kv-warn') + '">' + (d.status === 'ok' ? '\u2713' : '\u26A0') + ' ' + escapeHtml(d.status) + '</td></tr>';
    html += '<tr><th>版本</th><td>' + escapeHtml(d.version) + '</td></tr>';
    html += '<tr><th>运行时间</th><td>' + escapeHtml(fmtTime(d.uptime_seconds)) + '</td></tr>';
    html += '<tr><th>Redis</th><td class="' + (d.redis === 'connected' ? 'kv-ok' : 'kv-err') + '">' + escapeHtml(d.redis) + '</td></tr>';
    html += '<tr><th>数据库</th><td class="' + (d.database === 'connected' ? 'kv-ok' : 'kv-err') + '">' + escapeHtml(d.database) + '</td></tr>';
    html += '<tr><th>Agent 运行数</th><td>' + (d.agents_running || 0) + '</td></tr>';
    html += '</tbody></table>';
    return html;
  }

  function renderStatus(d) {
    if (d.error) return '<div class="tab-empty">\u26A0\uFE0F ' + escapeHtml(d.error) + '</div>';
    var html = '<table class="tab-table"><tbody>';
    html += '<tr><th>版本</th><td>' + escapeHtml(d.version || '\u2014') + '</td></tr>';
    html += '<tr><th>运行时间</th><td>' + escapeHtml(fmtTime(d.uptime_seconds)) + '</td></tr>';
    if (d.decision_stats) {
      var s = d.decision_stats;
      var ad = s.action_distribution || {};
      html += '<tr><th>决策统计</th><td>共 ' + (s.total || 0) + ' 条';
      if (ad.BUY) html += ', BUY: ' + ad.BUY;
      if (ad.SELL) html += ', SELL: ' + ad.SELL;
      if (ad.HOLD) html += ', HOLD: ' + ad.HOLD;
      html += '</td></tr>';
    }
    if (d.case_stats && !d.case_stats.error) {
      html += '<tr><th>案例统计</th><td>共 ' + (d.case_stats.total || 0) + ' 条</td></tr>';
    }
    if (d.latest_decision) {
      var ld = d.latest_decision;
      html += '<tr><th>最新决策</th><td>';
      html += '<span class="decision-action action-' + escapeHtml(ld.action) + '">' + escapeHtml(fmtAction(ld.action)) + '</span>';
      html += ' 置信度 ' + (ld.confidence * 100).toFixed(0) + '% | ' + escapeHtml(ld.provider);
      html += '<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(ld.reasoning || '') + '</div>';
      html += '</td></tr>';
    }
    html += '</tbody></table>';
    return html;
  }

  function renderReportList(d, name) {
    var hints = {
      '宏观报告': '由 Macro Agent 定期生成。如果无数据，请确认 Agent 已正常运行且数据库连接正常。',
      '信号报告': '由 Signal Agent 产生的技术信号报告。无数据时请检查 Signal Agent 运行状态。',
      '资金报告': '由 Trace Agent 产生的大单/资金流向报告。无数据时请检查 Trace Agent 运行状态。',
    };
    var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(name) + ' — 最近 ' + (d.count || 0) + ' 条</div>';
    if (!d.items || !d.items.length) {
      html += '<div class="tab-empty">暂无 ' + escapeHtml(name) + ' 数据</div>';
      html += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);line-height:1.6">' + escapeHtml(hints[name] || '') + '</div>';
      return html;
    }
    html += '<table class="tab-table"><thead><tr><th>时间</th><th>代码</th><th>摘要</th><th>置信度</th></tr></thead><tbody>';
    d.items.forEach(function(r) {
      html += '<tr><td class="kv-dim">' + escapeHtml(_ts(r.timestamp)) + '</td><td>' + escapeHtml(r.symbol || '\u2014') + '</td><td>' + escapeHtml(r.summary || '\u2014') + '</td><td>' + (r.confidence ? (r.confidence * 100).toFixed(0) + '%' : '\u2014') + '</td></tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  function renderDecisions(d) {
    var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83E\uDDE0 决策历史 — 共 ' + d.count + ' 条';
    if (d.stats) { var ad = d.stats.action_distribution || {}; html += ' (BUY: ' + (ad.BUY || 0) + ', SELL: ' + (ad.SELL || 0) + ', HOLD: ' + (ad.HOLD || 0) + ')'; }
    html += '</div>';
    if (!d.items || !d.items.length) {
      html += '<div class="tab-empty">暂无决策记录</div>';
      return html;
    }
    html += '<table class="tab-table"><thead><tr><th>时间</th><th>决策</th><th>置信度</th><th>AI</th><th>理由</th></tr></thead><tbody>';
    d.items.forEach(function(dec) {
      var did = dec.decision_id ? escapeHtml(dec.decision_id) : '';
      html += '<tr class="decision-row" data-id="' + did + '" onclick="window._DS.showDM(\'' + did + '\')" tabindex="0" role="button" aria-label="查看决策详情" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){window._DS.showDM(\'' + did + '\')}">';
      html += '<td class="kv-dim">' + escapeHtml(_ts(dec.timestamp)) + '</td>';
      html += '<td><span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(fmtAction(dec.action)) + '</span></td>';
      html += '<td>' + ((dec.confidence || 0) * 100).toFixed(0) + '%</td>';
      html += '<td class="kv-dim">' + escapeHtml(dec.provider_label || '\u2014') + '</td>';
      html += '<td class="kv-dim">' + escapeHtml((dec.reasoning || '').substring(0, 80)) + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  function renderBacktest(data) {
    var d = data.summary || data;
    var strategies = data.strategies;
    var html = '';

    if (strategies && strategies.strategies) {
      var stratArr = Object.keys(strategies.strategies).map(function(k) { var s = strategies.strategies[k]; s.name = k; return s; });
      html += _renderStrategyMgmt(stratArr);
    }

    html += '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCCA 股票池 × 7策略回测 — ' + d.count + ' 笔结果</div>';
    if (!d.results || !Object.keys(d.results).length) {
      html += '<div class="tab-empty">暂无回测数据（需先刷新缓存生成K线 + 手动回测）</div>';
      return html;
    }
    html += '<table class="tab-table"><thead><tr><th>股票</th><th>最优策略</th><th>夏普</th><th>索提诺</th><th>回撤%</th><th>胜率%</th><th>盈亏比</th><th>Alpha</th><th>评分</th></tr></thead><tbody>';
    Object.keys(d.results).forEach(function(sym) {
      var best = d.results[sym];
      var top = Object.keys(best)[0];
      if (!top) return;
      var r = best[top];
      var rowClass = r.score > 1 ? 'kv-ok' : r.score > 0 ? '' : 'kv-dim';
      var shrp = r.sharpe_ratio || r.sharpe || 0;
      html += '<tr role="button" tabindex="0" aria-label="查看 ' + escapeHtml(sym) + ' 回测详情" style="cursor:pointer" onclick="window._DS.btDetail(\'' + escapeHtml(sym) + '\')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){window._DS.btDetail(\'' + escapeHtml(sym) + '\')}">';
      html += '<td><span style="font-weight:700;color:var(--accent-blue)">' + escapeHtml(sym) + '</span></td>';
      html += '<td>' + escapeHtml(STRATEGY_LABELS[r.strategy] || STRATEGY_LABELS[top] || top) + '</td>';
      html += '<td class="' + (shrp > 0 ? 'kv-ok' : 'kv-dim') + '">' + shrp.toFixed(2) + '</td>';
      html += '<td class="' + ((r.sortino_ratio || 0) > 0 ? 'kv-ok' : 'kv-dim') + '">' + (r.sortino_ratio || 0).toFixed(2) + '</td>';
      html += '<td class="' + (r.max_drawdown_pct < 10 ? 'kv-ok' : 'kv-dim') + '">' + r.max_drawdown_pct + '%</td>';
      html += '<td class="' + (r.win_rate_pct > 50 ? 'kv-ok' : 'kv-dim') + '">' + r.win_rate_pct + '%</td>';
      html += '<td>' + r.profit_factor + '</td>';
      html += '<td class="' + ((r.alpha || 0) > 0 ? 'kv-ok' : 'kv-dim') + '">' + (r.alpha || 0).toFixed(2) + '%</td>';
      html += '<td class="' + rowClass + '"><strong>' + r.score + '</strong></td>';
      html += '</tr>';
    });
    html += '</tbody></table>';

    var strategyScores = {};
    Object.keys(d.results).forEach(function(sym) {
      var strats = d.results[sym];
      Object.keys(strats).forEach(function(name) {
        var s = strats[name];
        var shrp = s.sharpe_ratio || s.sharpe || 0;
        if (!strategyScores[name]) strategyScores[name] = { label: STRATEGY_LABELS[name] || name, sharpe: 0, win_rate: 0, count: 0 };
        strategyScores[name].sharpe += shrp;
        strategyScores[name].win_rate += s.win_rate_pct / 100;
        strategyScores[name].count += 1;
      });
    });
    var chartData = [];
    Object.keys(strategyScores).forEach(function(name) {
      var ss = strategyScores[name];
      chartData.push({ label: ss.label, sharpe: ss.count ? ss.sharpe / ss.count : 0, win_rate: ss.count ? ss.win_rate / ss.count : 0 });
    });

    html += '<div style="margin-top:16px"><h3 class="card-title">\uD83D\uDCC8 策略综合对比</h3></div>';
    _renderBacktestChart(chartData);

    return html;
  }

  function _renderBacktestChart(chartData) {
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        var bc = document.getElementById('backtest-chart');
        if (bc) {
          bc.style.display = 'block';
          Charts.renderBacktestBars('backtest-chart', chartData);
        }
      });
    });
  }

  function showBacktestDetail(symbol) {
    if (_btDetailSym === symbol) {
      var existing = document.getElementById('backtest-detail');
      if (existing) existing.style.display = 'none';
      _btDetailSym = null;
      return;
    }
    _btDetailSym = symbol;

    fetchAuth('/backtest/summary')
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var results = d.results || {};
        var strats = results[symbol];
        if (!strats) return;
        var top = Object.keys(strats)[0];
        var r = strats[top];
        if (!r || !r.equity_curve || !r.equity_curve.length) return;

        var container = document.getElementById('backtest-detail');
        if (!container) {
          container = document.createElement('div');
          container.id = 'backtest-detail';
          container.className = 'backtest-detail';
          document.getElementById('tab-panel').appendChild(container);
        }
        container.style.display = 'block';

        var lbl = r.strategy_label || r.strategy;
        var html = '<h3 class="card-title">\uD83D\uDCC8 ' + escapeHtml(symbol) + ' — ' + escapeHtml(lbl) + '</h3>';
        html += '<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;margin-bottom:10px;color:var(--text-secondary)">';
        html += '<span>夏普: <strong>' + (r.sharpe_ratio || 0).toFixed(2) + '</strong></span>';
        html += '<span>索提诺: <strong>' + (r.sortino_ratio || 0).toFixed(2) + '</strong></span>';
        html += '<span>胜率: <strong>' + r.win_rate_pct + '%</strong></span>';
        html += '<span>交易: <strong>' + r.total_trades + '</strong>笔</span>';
        html += '<span>Alpha: <strong>' + (r.alpha || 0).toFixed(2) + '%</strong></span>';
        html += '<span>Beta: <strong>' + (r.beta || 0).toFixed(2) + '</strong></span>';
        html += '<span>基准收益: <strong>' + (r.benchmark_return_pct || 0) + '%</strong></span>';
        html += '</div>';
        html += '<div id="backtest-equity-chart" class="chart-container" role="img" aria-label="权益曲线" style="height:300px"></div>';
        html += '<div id="backtest-dd-chart" class="chart-container" role="img" aria-label="回撤曲线" style="height:120px;margin-top:8px"></div>';
        container.innerHTML = html;

        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            Charts.renderEquityCurve('backtest-equity-chart', 'backtest-dd-chart', r.equity_curve, r.benchmark_curve, r.drawdown_curve, r.trade_markers);
          });
        });
      });
  }

  function renderRiskHistory(d) {
    if (!d || d.error) {
      return '<div class="tab-empty">\u26A0\uFE0F ' + escapeHtml(d && d.error || '暂无风控数据') + '</div>';
    }
    var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDEE1 风控否决历史 — 共 ' + (d.count || (d.overrides ? d.overrides.length : 0)) + ' 条</div>';
    var items = d.overrides || [];
    if (!items.length) {
      html += '<div class="tab-empty">暂无风控否决记录</div>';
      return html;
    }
    html += '<table class="tab-table"><thead><tr><th>时间</th><th>级别</th><th>规则</th><th>股票</th><th>详情</th></tr></thead><tbody>';
    items.forEach(function(ev) {
      var sev = ev.severity || ev.level || 'normal';
      var levelLabel = SEVERITY_LABELS[sev] || sev;
      var levelCls = sev === 'critical' ? 'kv-err' : sev === 'elevated' || sev === 'warning' ? 'kv-warn' : '';
      var reasonText = ev.reason || ev.rule || '\u2014';
      var actionCode = ev.action || ev.detail || '';
      var actionLabel = RISK_ACTION_LABELS[actionCode] || actionCode;
      html += '<tr>';
      html += '<td class="kv-dim">' + escapeHtml(_ts(ev.timestamp)) + '</td>';
      html += '<td class="' + levelCls + '"><strong>' + escapeHtml(levelLabel) + '</strong></td>';
      html += '<td>' + escapeHtml(reasonText) + '</td>';
      html += '<td>' + escapeHtml(ev.symbol || '\u2014') + '</td>';
      html += '<td class="kv-dim">' + escapeHtml(actionLabel.substring(0, 80)) + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  function _renderStrategyMgmt(strategies) {
    var html = '<div class="strat-mgmt">';
    html += '<div class="strat-mgmt-header"><h3>\u2699\uFE0F 策略管理</h3>';
    html += '<button class="strat-btn" onclick="window._DS.runBT()" style="font-size:12px;padding:6px 12px">\uD83D\uDD04 手动回测</button>';
    html += '</div>';
    html += '<table class="tab-table" style="font-size:13px"><thead><tr><th>策略</th><th>状态</th><th>连续失败</th><th>上次评分</th><th>操作</th></tr></thead><tbody>';
    strategies.forEach(function(s) {
      var active = s.status === 'active';
      var scoreStr = s.last_score != null ? s.last_score.toFixed(2) : '\u2014';
      html += '<tr>';
      html += '<td>' + escapeHtml(STRATEGY_LABELS[s.name] || s.name) + '</td>';
      html += '<td class="' + (active ? 'kv-ok' : 'kv-err') + '">' + (active ? '\u2713 活跃' : '\u2717 禁用') + '</td>';
      html += '<td class="' + (s.consecutive_losses > 3 ? 'kv-err' : '') + '">' + (s.consecutive_losses || 0) + '</td>';
      html += '<td>' + scoreStr + '</td>';
      html += '<td>' + (active ? '<span style="color:var(--text-muted);font-size:12px">运行中</span>' : '<button class="toggle-btn toggle-btn-enable" onclick="event.stopPropagation();window._DS.enableStrat(\'' + escapeHtml(s.name) + '\')">\u25B6 启用</button>') + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  function runManualBacktest() {
    var panel = $id('tab-panel');
    panel.innerHTML = '<div class="spinner">\u23F3 回测运行中...</div>';

    fetchAuth('/backtest/run', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) {
          panel.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>';
          return;
        }
        showToast('\u2705 回测完成: ' + d.count + ' 只股票, 变更: ' + (d.strategy_changes ? Object.keys(d.strategy_changes).length : 0), 'success');
        delete _tabCache['backtest'];
        loadTab('backtest');
      })
      .catch(function(e) {
        panel.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F ' + escapeHtml(e.message) + '</div>';
      });
  }

  function enableStrategy(name) {
    fetchAuth('/backtest/strategies/' + name + '/enable', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.status === 'active') {
          showToast('\u2705 策略已启用: ' + escapeHtml(name), 'success');
          delete _tabCache['backtest'];
          loadTab('backtest');
        }
      })
      .catch(function(e) {
        showToast('\u26A0\uFE0F ' + escapeHtml(e.message), 'warning');
      });
  }

  /* ── Decision Modal ── */
  function showDecisionModal(decisionId) {
    var modal = $id('decision-modal');
    var body = $id('decision-modal-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div class="spinner">\u23F3 加载中...</div>';

    fetchAuth('/decisions/' + decisionId)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) {
          body.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>';
          return;
        }
        var html = '';
        html += '<div class="modal-section"><div class="modal-label">决策</div><div class="modal-value"><span class="decision-action action-' + escapeHtml(d.action) + '">' + escapeHtml(fmtAction(d.action)) + '</span> 置信度 ' + ((d.confidence || 0) * 100).toFixed(0) + '%</div></div>';
        html += '<div class="modal-section"><div class="modal-label">AI 模型</div><div class="modal-value">' + escapeHtml(d.provider_label || '\u2014') + ' (' + escapeHtml(d.provider_status || '\u2014') + ')</div></div>';
        html += '<div class="modal-section"><div class="modal-label">时间</div><div class="modal-value">' + escapeHtml(_ts(d.timestamp)) + '</div></div>';
        html += '<div class="modal-section"><div class="modal-label">完整理由</div><div class="modal-value">' + escapeHtml(d.reasoning || '\u2014') + '</div></div>';
        if (d.evidence_sources && d.evidence_sources.length) {
          html += '<div class="modal-section"><div class="modal-label">证据来源</div><div class="modal-value">' + d.evidence_sources.map(function(s) { return '<div class="modal-chain-item">' + escapeHtml(s) + '</div>'; }).join('') + '</div></div>';
        }
        if (d.evidence_chain && d.evidence_chain.length) {
          html += '<div class="modal-section"><div class="modal-label">证据链</div><div class="modal-value">' + d.evidence_chain.map(function(s) { return '<div class="modal-chain-item">' + escapeHtml(typeof s === 'string' ? s : JSON.stringify(s)) + '</div>'; }).join('') + '</div></div>';
        }
        if (d.risk_override) {
          html += '<div class="modal-section"><div class="modal-label">\u26A0\uFE0F 风控否决</div><div class="modal-value" style="color:var(--color-yellow)">' + escapeHtml(JSON.stringify(d.risk_override)) + '</div></div>';
        }
        body.innerHTML = html;
      })
      .catch(function(e) {
        body.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F 加载失败: ' + escapeHtml(e.message) + '</div>';
      });
  }

  function closeDecisionModal() {
    $id('decision-modal').style.display = 'none';
  }

  /* ── Logs ── */
  function renderLogs(d) {
    if (!d || d.error) {
      return '<div class="tab-empty">\u26A0\uFE0F ' + escapeHtml(d && d.error || '加载失败') + '</div>';
    }
    var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCDC ' + escapeHtml(d.file || '') + ' — 最近 ' + d.count + ' 行</div>';
    html += '<div style="background:var(--bg-primary);border:1px solid var(--border-color);border-radius:8px;padding:12px;max-height:500px;overflow-y:auto;font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all">';
    if (d.lines && d.lines.length) {
      d.lines.forEach(function(line) {
        html += '<div style="border-bottom:1px solid var(--bg-tag);padding:2px 0">' + escapeHtml(line) + '</div>';
      });
    } else {
      html += '<span style="color:var(--text-muted)">暂无日志</span>';
    }
    html += '</div>';
    return html;
  }

  /* ── Paper Trading ── */
  function renderPaper(d) {
    if (!d || d.error) {
      return '<div class="tab-empty">\u26A0\uFE0F ' + escapeHtml(d && d.error || '加载失败') + '</div>';
    }
    var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCB0 纸上交易账户 — ' + escapeHtml(d.account_id || 'default') + '</div>';
    var pnlCls = (d.total_pnl_pct || 0) >= 0 ? 'trend-up' : 'trend-down';
    html += '<div class="result-stats" style="margin-bottom:12px">';
    html += '<div class="result-stat"><div>初始资金</div><div>' + (d.initial_capital || 0).toLocaleString() + '</div></div>';
    html += '<div class="result-stat"><div>当前权益</div><div>' + (d.total_equity || 0).toLocaleString() + '</div></div>';
    html += '<div class="result-stat"><div>可用资金</div><div>' + (d.capital || 0).toLocaleString() + '</div></div>';
    html += '<div class="result-stat"><div>盈亏</div><div class="' + pnlCls + '">' + (d.total_pnl_pct || 0) + '%</div></div>';
    html += '<div class="result-stat"><div>持仓数</div><div>' + (d.position_count || 0) + '</div></div>';
    html += '<div class="result-stat"><div>总订单</div><div>' + (d.total_orders || 0) + '</div></div>';
    html += '</div>';

    if (d.positions && d.positions.length) {
      html += '<h3 class="card-title">\uD83D\uDCBC 当前持仓</h3>';
      html += '<table class="tab-table"><thead><tr><th>代码</th><th>数量</th><th>均价</th><th>成本</th></tr></thead><tbody>';
      d.positions.forEach(function(p) {
        html += '<tr><td>' + escapeHtml(p.symbol) + '</td><td>' + p.quantity + '</td><td>' + p.avg_cost + '</td><td>' + (p.cost_basis || 0).toLocaleString() + '</td></tr>';
      });
      html += '</tbody></table>';
    }

    if (d.recent_orders && d.recent_orders.length) {
      html += '<h3 class="card-title" style="margin-top:12px">\uD83D\uDCCB 最近交易</h3>';
      html += '<table class="tab-table"><thead><tr><th>时间</th><th>代码</th><th>方向</th><th>数量</th><th>价格</th><th>理由</th></tr></thead><tbody>';
      d.recent_orders.slice(-10).reverse().forEach(function(o) {
        var actCls = o.action === 'BUY' ? 'trend-up' : o.action === 'SELL' ? 'trend-down' : 'kv-dim';
        var qtyStr = o.quantity > 0 ? o.quantity : '<span style="color:var(--text-muted)">' + escapeHtml(fmtAction(o.action)) + '</span>';
        html += '<tr><td class="kv-dim">' + escapeHtml(_ts(o.timestamp)) + '</td><td>' + escapeHtml(o.symbol) + '</td><td class="' + actCls + '">' + (o.quantity > 0 ? escapeHtml(fmtAction(o.action)) : '📋 ' + escapeHtml(fmtAction(o.action))) + '</td><td>' + qtyStr + '</td><td>' + o.price + '</td><td class="kv-dim">' + escapeHtml((o.reason || '').substring(0, 40)) + '</td></tr>';
      });
      html += '</tbody></table>';
    } else {
      html += '<div class="tab-empty">暂无交易</div>';
      html += '<div style="margin-top:8px;font-size:12px;color:var(--text-muted);line-height:1.6">执行 AI 诊股后，系统会自动根据决策（BUY/SELL）在模拟账户中执行一笔纸上交易。请先在顶部输入框诊股。</div>';
    }
    return html;
  }

  /* ── Help ── */
  function renderHelp() {
    return '\
<div class="help-guide">\
<h2>&#x2753; Market Trace V6.0 使用指南</h2>\
\
<h3>&#x1F4E1; 系统概览</h3>\
<p>Market Trace V6.0 是一个 <strong>A/B 股量化分析系统</strong>，通过 5 个 Agent（宏观/信号/资金/风控/决策）协作 + 7 级 LLM 回退链，对全市场 5000+ A 股进行技术分析、策略扫描和 AI 决策。</p>\
<p>左侧仪表盘卡片实时展示系统健康状态，下方 Tab 面板提供详细数据查阅，底部提供选股策略和全市场扫描功能。</p>\
\
<hr style="border-color:var(--border-color);margin:16px 0">\
<h2>&#x1F4CB; 仪表盘卡片</h2>\
\
<h3>&#x1F9ED; 风险偏好指数 RAI</h3>\
<p>显示当前市场的<strong>Risk Appetite Index</strong>（0~1），反映市场投机情绪。点击卡片跳转到<strong>宏观报告</strong> Tab。</p>\
<table class="tab-table" style="margin-top:6px">\
<tr><td style="color:var(--color-green)">RAI &ge; 0.55</td><td>市场乐观，风险偏好高</td></tr>\
<tr><td style="color:var(--color-yellow)">0.45 &le; RAI &lt; 0.55</td><td>震荡，方向不明</td></tr>\
<tr><td style="color:var(--color-red)">RAI &lt; 0.45</td><td>市场悲观，避险情绪浓</td></tr>\
</table>\
\
<h3>&#x1F916; 运行 Agent</h3>\
<p>展示 5 个 Agent 的存活状态。绿点亮起表示该 Agent 正常运行。点击跳转到<strong>健康检查</strong> Tab。</p>\
<ul>\
<li><strong>宏观 Macro</strong> &mdash; 采集指数、计算 RAI</li>\
<li><strong>信号 Signal</strong> &mdash; 计算 14 项技术指标</li>\
<li><strong>资金 Trace</strong> &mdash; 监控资金流向、大单异动</li>\
<li><strong>风控 Risk</strong> &mdash; 实时风险监控、否决异常决策</li>\
<li><strong>决策 Chief</strong> &mdash; 综合多源证据，输出 BUY/SELL/HOLD</li>\
</ul>\
\
<h3>&#x1F4E1; AI 决策链</h3>\
<p>系统使用<strong>七级 LLM 回退链</strong>确保决策不中断。绿勾表示该级 API Key 已配置可用，红叉表示未配置。</p>\
<p><code>DeepSeek Chat &rarr; DeepSeek Reasoner &rarr; Gemini K1 &rarr; Gemini K2 &rarr; GLM Flash &rarr; 硅基流动 &rarr; 百度千帆 &rarr; 纯规则</code></p>\
<p>任一环节熔断或超时自动降级到下一级，最终由纯规则兜底。</p>\
\
<h3>&#x1F6E1; 风控闭环</h3>\
<p>Risk Agent 实时监控市场风险和 AI 决策质量。当出现异常时自动否决决策或降权置信度。点击跳转到<strong>风控历史</strong> Tab。</p>\
\
<h3>&#x1F4BC; 持仓列表</h3>\
<p>添加关注的股票，系统显示实时价格和涨跌幅。<strong>点击股票名称</strong>可快速诊股，<strong>拖拽</strong>可自行排序，点击 <strong>&times;</strong> 可移除。<strong>"刷新列表"</strong>按钮手动刷新所有持仓的实时价格。</p>\
\
<h3>&#x1F4C8; 最新决策</h3>\
<p>显示最近一次 AI 综合决策的结果（买入/卖出/持仓观望/等待），包含置信度和推理理由。点击跳转到<strong>决策历史</strong> Tab。</p>\
\
<hr style="border-color:var(--border-color);margin:16px 0">\
<h2>&#x1F4CA; Tab 面板</h2>\
\
<h3>&#x1FA7A; 健康检查</h3>\
<p>查看系统运行状态：版本号、运行时间、Redis/数据库连接、LLM 链路配置、Agent 运行数。</p>\
\
<h3>&#x1F4CB; 状态详情</h3>\
<p>查看运行统计：决策统计（共多少条/BUY多少/SELL多少）、案例统计、最近一次决策详情。</p>\
\
<h3>&#x1F4CA; 宏观报告</h3>\
<p>由<strong>Macro Agent</strong> 定期生成的宏观分析报告。包含 RAI 指数、市场情绪评估、宏观研判。数据来自数据库，需 Agent 正常产出报告才有内容。</p>\
<p class="kv-dim">提示：如果此 Tab 无数据，说明 Agent 尚未产出报告或 Redis/数据库未就绪。</p>\
\
<h3>&#x1F4C9; 信号报告</h3>\
<p>由<strong>Signal Agent</strong> 产生的技术信号报告。记录各股票的技术指标计算结果和策略信号命中情况。</p>\
<p class="kv-dim">提示：如果此 Tab 无数据，请确认 Signal Agent 已正常运行且数据库连接正常。</p>\
\
<h3>&#x1F4B9; 资金报告</h3>\
<p>由<strong>Trace Agent</strong> 产生的资金流向报告。监控大单异动、主力资金方向、成交量异常等。</p>\
<p class="kv-dim">提示：如果此 Tab 无数据，请确认 Trace Agent 已正常运行。</p>\
\
<h3>&#x1F9E0; 决策历史</h3>\
<p>展示最近 10 条 AI 决策记录。每行显示决策动作、置信度、AI 来源和理由摘要。<strong>点击行</strong>可弹出详情弹窗，查看完整推理链、证据来源和风控否决信息。</p>\
<p>按 <kbd>Esc</kbd> 关闭弹窗。</p>\
\
<h3>&#x1F6E1; 风控历史</h3>\
<p>记录最近 20 条风控否决事件。包含严重级别（正常/警告/危险）、否决规则、相关股票和处理动作。</p>\
\
<h3>&#x1F4CA; 策略回测</h3>\
<p>查看股票池 &times; 7 策略的回测结果。表格展示夏普比率、索提诺比率、最大回撤、胜率、Alpha/Beta 等指标。</p>\
<p><strong>点击股票行</strong>可展开权益曲线、回撤曲线和买卖标记。</p>\
<p><strong>"策略管理"</strong>面板显示各策略状态（活跃/禁用）、连续失败次数和评分。禁用的策略可手动重新启用。</p>\
<p><strong>"手动回测"</strong>按钮触发新一轮回测计算。</p>\
\
<h3>&#x1F4DC; 系统日志</h3>\
<p>查看最近 100 行服务器日志（markdown 格式）。用于排查异常、了解系统运行状态。启动日志、Agent 日志、API 调用日志均在此处。</p>\
\
<h3>&#x1F4B0; 纸上交易</h3>\
<p>模拟账户的交易记录。每次 AI 诊股后，系统<strong>自动</strong>根据决策执行一笔模拟交易。此 Tab 显示：初始资金、当前权益、盈亏、持仓明细和最近交易记录。</p>\
<p class="kv-dim">提示：如果此 Tab 显示空账户，请先执行诊股触发模拟交易。</p>\
\
<hr style="border-color:var(--border-color);margin:16px 0">\
<h2>&#x1F3AF; 核心功能</h2>\
\
<h3>&#x1F50D; 诊股</h3>\
<p>在顶部输入框输入股票代码（如 <code>000001</code> 或 <code>600519</code>），点击<strong>"诊股"</strong>或按回车。</p>\
<p>系统将：</p>\
<ol>\
<li>拉取 K 线数据（60 日）</li>\
<li>计算 14 项技术指标（RSI/MACD/布林带/KDJ/ATR/支撑阻力/均线趋势）</li>\
<li>检测 7 策略信号命中（强势突破/超跌反弹/主力介入/风险预警/金叉/放量/RSI反转）</li>\
<li>通过 AI 七级回退链输出交易决策（BUY/SELL/HOLD）</li>\
<li>显示 K 线图、仓位建议，并自动记录纸上交易</li>\
</ol>\
<p>如果 LLM 链路全部不可用，会显示<strong>红色降级警告</strong>横幅，说明已降级到纯规则兜底。</p>\
\
<h3>&#x1F3AF; 选股策略（股票池扫描）</h3>\
<p>对配置的 <code>stock_pool</code>（约 48 只）做指定策略筛选。4 个按钮对应 4 个策略：</p>\
<ul>\
<li><strong>&#x1F525; 强势突破</strong> &mdash; 价格突破近期高点 + 放量确认</li>\
<li><strong>&#x1F48E; 超跌反弹</strong> &mdash; RSI 超卖 + 近期跌幅较大</li>\
<li><strong>&#x1F4B0; 主力介入</strong> &mdash; 放量上涨 + 资金流入迹象</li>\
<li><strong>&#x1F4C9; 风险预警</strong> &mdash; RSI 偏高 + 高位放量下跌</li>\
</ul>\
<p class="kv-dim">提示：匹配 0 只代表股票池中暂无符合该策略条件的股票，或缓存 K 线数据不足（需 &ge; 20 条）。</p>\
\
<h3>&#x1F50D; 全市场扫描</h3>\
<p>对全市场 5000+ A 股做批量策略筛选。两阶段扫描：先按实时涨跌幅粗筛，再对有缓存 K 线的股票做深度策略验证。</p>\
<ul>\
<li><strong>7 个绿色按钮</strong> &mdash; 单策略全市场扫描（突破/超跌/主力/风险/金叉/放量/RSI反转）</li>\
<li><strong>&#x1F9E0; 智能综合（紫色）</strong> &mdash; 7 策略综合评分，取每只股票的最优策略排行</li>\
</ul>\
<p>结果按量比和涨跌幅排序，可直接点<strong>"诊股"</strong>按钮跳转详细分析。</p>\
<p class="kv-dim">提示：扫描需要缓存的 K 线数据。如果系统刚启动或缓存未就绪，可能命中较少。等待 prefetch 预热完成（约 30 秒）后重试。</p>\
\
<hr style="border-color:var(--border-color);margin:16px 0">\
<h2>&#x26A1; 快捷操作</h2>\
<ul>\
<li>持仓列表<strong>拖拽</strong> &rarr; 自定义排序</li>\
<li>持仓列表<strong>点击股票名</strong> &rarr; 快速诊股</li>\
<li>回测表格<strong>点击股票行</strong> &rarr; 展开权益曲线</li>\
<li>扫描结果<strong>点击"诊股"</strong> &rarr; 跳转分析</li>\
<li>风控卡片<strong>点击</strong> &rarr; 跳转风控历史</li>\
<li>决策历史<strong>点击行</strong> &rarr; 查看完整决策弹窗</li>\
<li>弹窗按 <kbd>Esc</kbd> &rarr; 关闭</li>\
<li>Tab 面板右上角 <strong>&#x1F504;</strong> &rarr; 刷新当前面板</li>\
</ul>\
\
<hr style="border-color:var(--border-color);margin:16px 0">\
<h2>&#x1F4CA; 技术指标速查</h2>\
<table class="tab-table">\
<thead><tr><th>指标</th><th>说明</th><th>信号判断</th></tr></thead>\
<tbody>\
<tr><td>RSI</td><td>相对强弱指数</td><td>&gt;70 超买看空，&lt;30 超卖看多</td></tr>\
<tr><td>MACD</td><td>异同移动均线</td><td>金叉(DIF上穿DEA)看多，死叉看空</td></tr>\
<tr><td>布林带</td><td>价格波动通道</td><td>触及上轨看空，触及下轨看多，带宽收窄预示变盘</td></tr>\
<tr><td>KDJ</td><td>随机指标</td><td>J&gt;100 超买，J&lt;0 超卖</td></tr>\
<tr><td>ATR</td><td>平均真实波幅</td><td>衡量波动率，越大越活跃</td></tr>\
<tr><td>MA5/10/20/60</td><td>移动均线</td><td>多头排列(短>长)看多，空头排列看空</td></tr>\
<tr><td>RAI</td><td>风险偏好指数</td><td>&gt;0.55 乐观，&lt;0.45 悲观</td></tr>\
<tr><td>量比</td><td>当前量/均量</td><td>&gt;1.5 显著放量，&lt;0.5 缩量</td></tr>\
<tr><td>Sharpe</td><td>风险调整收益</td><td>&gt;1 良好，&gt;2 优秀</td></tr>\
<tr><td>Sortino</td><td>下行风险调整</td><td>&gt;2 优秀</td></tr>\
<tr><td>Alpha</td><td>超额收益</td><td>&gt;0 跑赢基准</td></tr>\
<tr><td>Beta</td><td>系统性风险</td><td>&gt;1 比市场波动大</td></tr>\
</tbody>\
</table>\
</div>\
';
  }

  /* ── Watchlist ── */
  function refreshWatchlist() {
    var btn = $id('watchlist-refresh-btn');
    btn.disabled = true;
    btn.textContent = '\u23F3';
    $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">刷新中...</div>';

    fetchAuth('/watchlist')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(wl) {
        $id('watchlist-items').innerHTML = wl && wl.items ? _renderWatchlistItems(_applyWlSortOrder(wl.items)) : '<div style="color:var(--text-muted);font-size:13px">加载失败</div>';
        if (wl && wl.items) {
          wl.items.forEach(function(it) { if (it.name) _stockNames[it.symbol] = it.name; });
        }
      })
      .catch(function() {
        $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">加载失败</div>';
      })
      .finally(function() {
        btn.disabled = false;
        btn.textContent = '刷新列表';
      });
  }

  function addToWatchlist() {
    var input = $id('watchlist-input');
    var sym = input.value.trim();
    if (!sym) { showToast('请输入股票代码', 'warning'); return; }
    var btn = $id('watchlist-add-btn');
    btn.disabled = true;
    btn.textContent = '...';

    fetchAuth('/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym }) })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) { showToast(d.error, 'warning'); return; }
        input.value = '';
        showToast('\u2705 已添加: ' + escapeHtml(sym), 'success');
        load();
      })
      .catch(function(e) { showToast('\u26A0\uFE0F ' + escapeHtml(e.message), 'warning'); })
      .finally(function() { btn.disabled = false; btn.textContent = '+ 添加'; });
  }

  function removeFromWatchlist(symbol) {
    if (!confirm('确认移除 ' + symbol + '？')) return;
    fetchAuth('/watchlist/' + symbol, { method: 'DELETE' })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.removed) { showToast('\u2705 已移除: ' + escapeHtml(symbol), 'success'); load(); }
      })
      .catch(function(e) { showToast('\u26A0\uFE0F ' + escapeHtml(e.message), 'warning'); });
  }

  /* ── Event Delegation for dynamic buttons ── */
  document.addEventListener('click', function(e) {
    var diagBtn = e.target.closest ? e.target.closest('[data-diag]') : null;
    if (diagBtn) {
      var sym = diagBtn.getAttribute('data-diag');
      if (sym) $id('stock-input').value = sym;
      analyzeStock();
    }
  });

  /* ── Keyboard ── */
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && $id('decision-modal').style.display === 'flex') {
      closeDecisionModal();
    }
  });

  $id('watchlist-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') addToWatchlist();
  });

  $id('stock-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') analyzeStock();
  });

  $id('decision-modal').addEventListener('click', function(e) {
    if (e.target === this) closeDecisionModal();
  });

  /* ── Card → Tab click handlers ── */
  _safeCardClick('风险偏好指数', 'reports');
  _safeCardClick('运行中的 Agent', 'health');
  _safeCardClick('AI 决策链', 'decisions');
  _safeCardClick('风控闭环', 'risk-history');
  _safeClick($id('decision-area'), 'decisions');

  /* ── Polling ── */
  function _updateCountdown() {
    var el = $id('refresh-countdown');
    if (el) el.textContent = _countdownSec + 's';
  }

  function _startCountdown() {
    _countdownSec = Math.floor(POLL_INTERVAL / 1000);
    _updateCountdown();
    setInterval(function() {
      _countdownSec -= 1;
      if (_countdownSec <= 0) _countdownSec = Math.floor(POLL_INTERVAL / 1000);
      _updateCountdown();
    }, 1000);
  }

  function startPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _showSkeletons();
    _updateCountdown();
    load();
    _pollTimer = setInterval(function() {
      if (document.hidden) return;
      _countdownSec = Math.floor(POLL_INTERVAL / 1000);
      _updateCountdown();
      load();
    }, POLL_INTERVAL);
  }

  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) load();
  });

  /* ── Global Error Handling ── */
  window.addEventListener('error', function(e) {
    var msg = '[JS Error] ' + (e.message || '未知错误') + ' @ ' + (e.filename || '').split('/').pop() + ':' + (e.lineno || '?');
    console.error(msg, e.error);
    showToast(msg, 'error');
  });
  window.addEventListener('unhandledrejection', function(e) {
    var msg = '[Promise Error] ' + (e.reason && e.reason.message || '未知错误');
    console.error(msg, e.reason);
    showToast(msg, 'error');
  });

  /* ── Expose public API for onclick handlers in rendered HTML ── */
  window._DS = {
    diag: function(sym) { $id('stock-input').value = sym; analyzeStock(); },
    rmwl: removeFromWatchlist,
    showDM: showDecisionModal,
    btDetail: showBacktestDetail,
    runBT: runManualBacktest,
    enableStrat: enableStrategy,
  };

  // Expose functions used directly in HTML onclick attributes
  window.analyzeStock = analyzeStock;
  window.addToWatchlist = addToWatchlist;
  window.refreshWatchlist = refreshWatchlist;
  window.removeFromWatchlist = removeFromWatchlist;
  window.screenStocks = screenStocks;
  window.fullScan = fullScan;
  window.smartScan = smartScan;
  window.switchTab = switchTab;
  window.refreshActiveTab = refreshActiveTab;
  window.closeDecisionModal = closeDecisionModal;
  window.showDecisionModal = showDecisionModal;

  /* ── Init ── */
  _loadWlSortOrder();
  _initScrollTopBtn();
  _initWlDragDrop();
  _startCountdown();
  switchTab('health');
  startPoll();

})();
