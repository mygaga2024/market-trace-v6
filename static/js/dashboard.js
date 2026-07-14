/* ──────────────────────────────────────
   Main Dashboard IIFE
   ────────────────────────────────────── */
(function() {
  'use strict';

  /* ── Local aliases from window.MT6 ── */
  var E = window.MT6.escapeHtml;
  var Q = window.MT6.$id;
  var S = window.MT6;
  var st = S.state;

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

  /* ── Safe card click-to-tab ── */
  function _safeClick(el, tab) {
    if (el) el.addEventListener('click', function() { switchTab(tab); });
  }
  function _safeCardClick(ariaLabel, tab) {
    var card = document.querySelector('.card[aria-label="' + ariaLabel + '"]');
    if (card) card.addEventListener('click', function() { switchTab(tab); });
  }

  /* ── Watchlist Drag & Drop Sort (handlers) ── */
  var _wlDragSrc = null;

  function _initWlDragDrop() {
    var container = Q('watchlist-items');
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
        S._wlSortOrder = newOrder;
        S._saveWlSortOrder();
        load();
      }
    });
  }

  /* ── Tab Infrastructure ── */
  var TAB_FETCHERS = {
    health:       function() { return S.fetchAuth('/health/detail').then(function(r) { return r.json(); }); },
    status:       function() { return S.fetchAuth('/status').then(function(r) { return r.json(); }); },
    reports:      function() { return S.fetchAuth('/reports/macro?limit=5').then(function(r) { return r.json(); }); },
    signal:       function() { return S.fetchAuth('/reports/signal?limit=5').then(function(r) { return r.json(); }); },
    trace:        function() { return S.fetchAuth('/reports/trace?limit=5').then(function(r) { return r.json(); }); },
    decisions:    function() { return S.fetchAuth('/decisions?limit=10').then(function(r) { return r.json(); }); },
    'risk-history': function() { return S.fetchAuth('/risk/overrides?limit=20').then(function(r) { return r.json(); }); },
    backtest:     function() {
      return Promise.all([
        S.fetchAuth('/backtest/summary').then(function(r) { return r.json(); }),
        S.fetchAuth('/backtest/strategies').then(function(r) { return r.json(); }).catch(function() { return null; })
      ]).then(function(results) { return { summary: results[0], strategies: results[1] }; });
    },
    logs:         function() { return S.fetchAuth('/logs?lines=100').then(function(r) { return r.json(); }); },
    paper:        function() { return S.fetchAuth('/paper/account').then(function(r) { return r.json(); }); },
    help:         function() { return Promise.resolve({}); },
  };

  var TAB_RENDERERS = {
    health:       window.TAB_REPORTS.renderHealth,
    status:       window.TAB_REPORTS.renderStatus,
    reports:      function(d) { return window.TAB_REPORTS.renderReportList(d, '宏观报告'); },
    signal:       function(d) { return window.TAB_REPORTS.renderReportList(d, '信号报告'); },
    trace:        function(d) { return window.TAB_REPORTS.renderReportList(d, '资金报告'); },
    decisions:    window.TAB_REPORTS.renderDecisions,
    'risk-history': window.TAB_RISK.renderRiskHistory,
    backtest:     window.TAB_BACKTEST.renderBacktest,
    logs:         window.TAB_REPORTS.renderLogs,
    paper:        window.TAB_REPORTS.renderPaper,
    help:         window.TAB_REPORTS.renderHelp,
  };

  /* ── Main load() ── */
  function load() {
    Promise.all([
      S.fetchAuth('/health/detail').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/status').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/reports/macro/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/reports/signal/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/reports/trace/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/risk/status').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/watchlist').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      S.fetchAuth('/api/market/index').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    ]).then(function(results) {
      var h = results[0], stRes = results[1], mr = results[2], lr = results[3], dr = results[4], rk = results[5], wl = results[6], mi = results[7];

      S._clearSkeletons();

      if (!h) return;

      var ok = h.status === 'ok';
      Q('sys-status').className = 'badge ' + (ok ? 'badge-ok' : 'badge-warn');
      Q('sys-status').innerHTML = '<span aria-hidden="true">' + (ok ? '\u25CF' : '\u25D0') + '</span> ' + (ok ? '正常' : '降级');
      Q('uptime').textContent = S.fmtTime(h.uptime_seconds);
      var fv = document.getElementById('footer-version');
      if (fv && h.version) fv.textContent = h.version;

      if (h.agents) {
        var dots = document.querySelectorAll('.agent-dot .dot');
        var names = ['macro', 'signal', 'trace', 'risk', 'chief'];
        var alive = names.filter(function(n) { return h.agents[n]; }).length;
        Q('agent-count').textContent = alive + '/5';
        names.forEach(function(n, i) {
          if (dots[i]) dots[i].className = 'dot ' + (h.agents[n] ? 'dot-on' : 'dot-off');
        });
      }

      var llmHtml = '';
      if (h.llm_chain) {
        S.LLM_TIERS.forEach(function(t) {
          var p = h.llm_chain[t];
          if (!p) return;
          var icon = p.api_key_configured ? '\u2713' : '\u2717';
          var cls = p.api_key_configured ? 'llm-status-on' : 'llm-status-off';
          llmHtml += '<div class="llm-row"><span class="llm-name ' + cls + '">' + icon + ' ' + E(p.provider) + '</span><span style="font-size:12px;color:var(--text-secondary)">' + E(p.model) + '</span></div>';
        });
      }
      Q('llm-chain').innerHTML = llmHtml || '未配置';

      if (rk) {
        var riskLevel = rk.level || 'normal';
        var levelLabels = { normal: '正常', elevated: '关注', critical: '危险' };
        var levelCls = 'risk-' + riskLevel;
        Q('risk-level-display').innerHTML = '<span class="risk-indicator ' + levelCls + '">' + (levelLabels[riskLevel] || riskLevel) + '</span>';
        Q('risk-override-count').textContent = rk.daily_overrides || 0;
        Q('risk-event-count').textContent = rk.total_overrides || 0;
      } else {
        Q('risk-level-display').innerHTML = '<span class="risk-indicator risk-loading">无数据</span>';
        Q('risk-override-count').textContent = '\u2014';
        Q('risk-event-count').textContent = '\u2014';
      }

      Q('watchlist-items').innerHTML = wl && wl.items ? S._renderWatchlistItems(S._applyWlSortOrder(wl.items)) : '<div style="color:var(--text-muted);font-size:13px">加载中...</div>';
      if (wl && wl.items) {
        wl.items.forEach(function(it) { if (it.name) st._stockNames[it.symbol] = it.name; });
      }

      S._renderMarketIndex(mi);

      if (mr && mr.data && mr.data.risk_appetite_index != null) {
        var rai = mr.data.risk_appetite_index;
        var interp = mr.data.interpretation || {};
        var cls = rai >= 0.55 ? 'rai-good' : rai >= 0.45 ? 'rai-warm' : 'rai-bad';
        var pct = (rai * 100).toFixed(0);
        Q('rai-value').textContent = rai.toFixed(2);
        Q('rai-value').className = 'rai-value ' + cls;
        Q('rai-label').textContent = interp.regime || '';
        var bar = Q('rai-bar');
        bar.style.width = pct + '%';
        bar.style.background = rai >= 0.55 ? 'var(--color-rise)' : rai >= 0.45 ? 'var(--color-yellow)' : 'var(--color-fall)';
      } else {
        Q('rai-value').textContent = '\u2014';
        Q('rai-label').textContent = '等待数据';
      }

      var dec = stRes && stRes.latest_decision;
      if (dec) {
        var area = Q('decision-area');
        area.style.display = 'block';
        Q('decision-action').innerHTML = '<span class="decision-action action-' + E(dec.action) + '">' + E(S.fmtAction(dec.action)) + '</span>';
        Q('decision-conf').textContent = (dec.confidence * 100).toFixed(0) + '%';
        Q('decision-reason').textContent = dec.reasoning || '';
        Q('decision-provider').textContent = dec.provider || '\u2014';
      }
    }).catch(function(e) {
      console.error(e);
      S._clearSkeletons();
    });
  }

  /* ── Tab Switching ── */
  function switchTab(tab) {
    st._activeTab = tab;
    var buttons = document.querySelectorAll('.tab-btn');
    buttons.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
      b.setAttribute('aria-selected', b.getAttribute('data-tab') === tab ? 'true' : 'false');
    });
    var toolbarButtons = document.querySelectorAll('.toolbar-btn');
    toolbarButtons.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    var bc = Q('backtest-chart');
    if (bc) bc.style.display = (tab === 'backtest') ? 'block' : 'none';
    loadTab(tab);
    Q('tab-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function refreshActiveTab() {
    delete st._tabCache[st._activeTab];
    loadTab(st._activeTab);
  }

  function loadTab(tab) {
    var panel = Q('tab-panel');
    panel.innerHTML = '<div class="spinner">\u23F3 加载中...</div>';

    var entry = st._tabCache[tab];
    if (entry && entry.html && Date.now() - entry.ts < 120000) {
      panel.innerHTML = entry.html;
      return;
    }

    var fn = TAB_FETCHERS[tab];
    if (!fn) { panel.innerHTML = '<div class="tab-empty">未知面板</div>'; return; }

    fn().then(function(data) {
      var renderer = TAB_RENDERERS[tab];
      var html = renderer ? renderer(data) : '<pre>' + E(JSON.stringify(data, null, 2)) + '</pre>';
      st._tabCache[tab] = { html: html, ts: Date.now() };
      panel.innerHTML = html;
    }).catch(function(e) {
      panel.innerHTML = '<div class="tab-empty">\u26A0\uFE0F 加载失败: ' + E(e.message || '网络错误') + '</div>';
    });
  }

  /* ── Decision Modal ── */
  function showDecisionModal(decisionId) {
    var modal = Q('decision-modal');
    var body = Q('decision-modal-body');
    modal.style.display = 'flex';
    body.innerHTML = '<div class="spinner">\u23F3 加载中...</div>';

    S.fetchAuth('/decisions/' + decisionId)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.error) {
          body.innerHTML = '<div class="error-banner" role="alert">' + E(d.error) + '</div>';
          return;
        }
        var html = '';
        html += '<div class="modal-section"><div class="modal-label">决策</div><div class="modal-value"><span class="decision-action action-' + E(d.action) + '">' + E(S.fmtAction(d.action)) + '</span> 置信度 ' + ((d.confidence || 0) * 100).toFixed(0) + '%</div></div>';
        html += '<div class="modal-section"><div class="modal-label">AI 模型</div><div class="modal-value">' + E(d.provider_label || '\u2014') + ' (' + E(d.provider_status || '\u2014') + ')</div></div>';
        html += '<div class="modal-section"><div class="modal-label">时间</div><div class="modal-value">' + E(S._ts(d.timestamp)) + '</div></div>';
        html += '<div class="modal-section"><div class="modal-label">完整理由</div><div class="modal-value">' + E(d.reasoning || '\u2014') + '</div></div>';
        if (d.evidence_sources && d.evidence_sources.length) {
          html += '<div class="modal-section"><div class="modal-label">证据来源</div><div class="modal-value">' + d.evidence_sources.map(function(s) { return '<div class="modal-chain-item">' + E(s) + '</div>'; }).join('') + '</div></div>';
        }
        if (d.evidence_chain && d.evidence_chain.length) {
          html += '<div class="modal-section"><div class="modal-label">证据链</div><div class="modal-value">' + d.evidence_chain.map(function(s) { return '<div class="modal-chain-item">' + E(typeof s === 'string' ? s : JSON.stringify(s)) + '</div>'; }).join('') + '</div></div>';
        }
        if (d.risk_override) {
          html += '<div class="modal-section"><div class="modal-label">\u26A0\uFE0F 风控否决</div><div class="modal-value" style="color:var(--color-yellow)">' + E(JSON.stringify(d.risk_override)) + '</div></div>';
        }
        body.innerHTML = html;
      })
      .catch(function(e) {
        body.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F 加载失败: ' + E(e.message) + '</div>';
      });
  }

  function closeDecisionModal() {
    Q('decision-modal').style.display = 'none';
  }

  /* ── Expose load / loadTab for tab modules ── */
  window.MT6.load = load;
  window.MT6.loadTab = loadTab;

  /* ── Event Delegation for dynamic buttons ── */
  document.addEventListener('click', function(e) {
    var diagBtn = e.target.closest ? e.target.closest('[data-diag]') : null;
    if (diagBtn) {
      var sym = diagBtn.getAttribute('data-diag');
      if (sym) Q('stock-input').value = sym;
      window.TAB_ANALYZE.analyzeStock();
    }
  });

  /* ── Keyboard ── */
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && Q('decision-modal').style.display === 'flex') {
      closeDecisionModal();
    }
  });

  Q('watchlist-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') window.TAB_WATCHLIST.addToWatchlist();
  });

  Q('stock-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') window.TAB_ANALYZE.analyzeStock();
  });

  Q('decision-modal').addEventListener('click', function(e) {
    if (e.target === this) closeDecisionModal();
  });

  /* ── Card → Tab click handlers ── */
  _safeCardClick('风险偏好指数', 'reports');
  _safeCardClick('运行中的 Agent', 'health');
  _safeCardClick('AI 决策链', 'decisions');
  _safeCardClick('风控闭环', 'risk-history');
  _safeClick(Q('decision-area'), 'decisions');

  /* ── Polling ── */
  var _pollTimer = null;

  function _updateCountdown() {
    var el = Q('refresh-countdown');
    if (el) el.textContent = st._countdownSec + 's';
  }

  function _startCountdown() {
    st._countdownSec = Math.floor(S.POLL_INTERVAL / 1000);
    _updateCountdown();
    setInterval(function() {
      st._countdownSec -= 1;
      if (st._countdownSec <= 0) st._countdownSec = Math.floor(S.POLL_INTERVAL / 1000);
      _updateCountdown();
    }, 1000);
  }

  function startPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    S._showSkeletons();
    _updateCountdown();
    load();
    _pollTimer = setInterval(function() {
      if (document.hidden) return;
      st._countdownSec = Math.floor(S.POLL_INTERVAL / 1000);
      _updateCountdown();
      load();
    }, S.POLL_INTERVAL);
  }

  document.addEventListener('visibilitychange', function() {
    if (!document.hidden) load();
  });

  /* ── Global Error Handling ── */
  window.addEventListener('error', function(e) {
    var msg = '[JS Error] ' + (e.message || '未知错误') + ' @ ' + (e.filename || '').split('/').pop() + ':' + (e.lineno || '?');
    console.error(msg, e.error);
    S.showToast(msg, 'error');
  });
  window.addEventListener('unhandledrejection', function(e) {
    var msg = '[Promise Error] ' + (e.reason && e.reason.message || '未知错误');
    console.error(msg, e.reason);
    S.showToast(msg, 'error');
  });

  /* ── Expose public API for onclick handlers in rendered HTML ── */
  window._DS = {
    diag: function(sym) { Q('stock-input').value = sym; window.TAB_ANALYZE.analyzeStock(); },
    rmwl: window.TAB_WATCHLIST.removeFromWatchlist,
    showDM: showDecisionModal,
    btDetail: window.TAB_BACKTEST.showBacktestDetail,
    runBT: window.TAB_BACKTEST.runManualBacktest,
    enableStrat: window.TAB_BACKTEST.enableStrategy,
  };

  // Expose functions used directly in HTML onclick attributes
  window.analyzeStock = function() { window.TAB_ANALYZE.analyzeStock(); };
  window.addToWatchlist = function() { window.TAB_WATCHLIST.addToWatchlist(); };
  window.refreshWatchlist = function() { window.TAB_WATCHLIST.refreshWatchlist(); };
  window.removeFromWatchlist = function(sym) { window.TAB_WATCHLIST.removeFromWatchlist(sym); };
  window.screenStocks = function(s) { window.TAB_ANALYZE.screenStocks(s); };
  window.fullScan = function(s) { window.TAB_ANALYZE.fullScan(s); };
  window.smartScan = function() { window.TAB_ANALYZE.smartScan(); };
  window.switchTab = switchTab;
  window.refreshActiveTab = refreshActiveTab;
  window.closeDecisionModal = closeDecisionModal;
  window.showDecisionModal = showDecisionModal;

  /* ── Init ── */
  S._loadWlSortOrder();
  _initScrollTopBtn();
  _initWlDragDrop();
  _startCountdown();
  switchTab('health');
  startPoll();

})();
