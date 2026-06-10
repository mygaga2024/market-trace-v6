/* ──────────────────────────────────────
   Market Trace V6.0 — Dashboard Logic
   ────────────────────────────────────── */

// 认证通过 httpOnly cookie 自动发送，无需在 JS 中读取 token
function fetchAuth(url, options) {
  options = options || {};
  options.credentials = 'same-origin';  // 自动携带 httpOnly cookie
  return fetchWithRetry(url, options);
}

function fetchWithRetry(url, options, retries = 3, delay = 1000) {
  return fetch(url, options).then(function(r) {
    if (!r.ok && retries > 0 && r.status >= 500) {
      return new Promise(function(resolve) {
        setTimeout(function() { resolve(fetchWithRetry(url, options, retries - 1, delay * 2)); }, delay);
      });
    }
    return r;
  });
}

function escapeHtml(str) {
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

function $id(id) { return document.getElementById(id); }
function $(sel) { return document.querySelector(sel); }

function fmtTime(s) {
  var m = Math.floor(s / 60), h = Math.floor(m / 60);
  m %= 60;
  return h ? h + 'h' + m + 'm' : m + 'm' + Math.floor(s % 60) + 's';
}

var _pollTimer = null;
var _analyzeLoading = false;
var _screenAbort = null;
var _activeTab = 'health';
var _tabCache = {};

function startPoll() {
  if (_pollTimer) clearInterval(_pollTimer);
  load();
  _pollTimer = setInterval(function() {
    if (document.hidden) return;
    load();
  }, 30000);
}

document.addEventListener('visibilitychange', function() {
  if (!document.hidden) load();
});

function showToast(msg, type) {
  type = type || 'error';
  var el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.setAttribute('role', 'alert');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(function() { el.remove(); }, 5000);
}

/* ── Load Dashboard ── */
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
    ]);

    var h = results[0], st = results[1], mr = results[2], lr = results[3], dr = results[4], rk = results[5], wl = results[6];

    if (!h) return;

    var ok = h.status === 'ok';
    $id('sys-status').className = 'badge ' + (ok ? 'badge-ok' : 'badge-warn');
    $id('sys-status').innerHTML = '<span aria-hidden="true">' + (ok ? '\u25CF' : '\u25D0') + '</span> ' + (ok ? '正常' : '降级');
    $id('uptime').textContent = fmtTime(h.uptime_seconds);

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
      ['primary', 'secondary', 'tertiary'].forEach(function(t) {
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
      $id('risk-override-count').textContent = rk.override_count || 0;
      $id('risk-event-count').textContent = rk.event_count || 0;
    } else {
      $id('risk-level-display').innerHTML = '<span class="risk-indicator risk-loading">无数据</span>';
      $id('risk-override-count').textContent = '\u2014';
      $id('risk-event-count').textContent = '\u2014';
    }

    if (wl && wl.items) {
      var wlHtml = '';
      if (wl.items.length === 0) {
        wlHtml = '<div style="color:var(--text-muted);font-size:13px">暂无持仓</div>';
      } else {
        wl.items.forEach(function(item) {
          var changeCls = item.change_pct != null ? (item.change_pct >= 0 ? 'trend-up' : 'trend-down') : '';
          var changeStr = item.change_pct != null ? '<span class="' + changeCls + '"><span aria-hidden="true">' + (item.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + item.change_pct.toFixed(2) + '%</span>' : '\u2014';
          var priceStr = item.price != null ? item.price.toFixed(2) : '\u2014';
          var nameStr = item.name || '';
          var displayName = nameStr ? escapeHtml(nameStr) + ' <span style="color:var(--text-secondary);font-size:11px">' + escapeHtml(item.symbol) + '</span>' : escapeHtml(item.symbol);
          wlHtml += '<div class="wl-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg-tag);font-size:13px">';
          wlHtml += '<span style="cursor:pointer;flex:1" onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(item.symbol) + '\';analyzeStock()" title="点击诊股">' + displayName + '</span>';
          wlHtml += '<span style="margin:0 8px">' + priceStr + '</span>';
          wlHtml += '<span style="margin:0 8px;min-width:60px;text-align:right">' + changeStr + '</span>';
          wlHtml += '<button onclick="event.stopPropagation();removeFromWatchlist(\'' + escapeHtml(item.symbol) + '\')" style="background:none;border:none;color:var(--color-red);cursor:pointer;font-size:16px;padding:0 4px" title="移除" aria-label="移除 ' + escapeHtml(item.symbol) + '">\u00D7</button>';
          wlHtml += '</div>';
        });
      }
      $id('watchlist-items').innerHTML = wlHtml;
    } else {
      $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">加载中...</div>';
    }

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
      $id('decision-action').innerHTML = '<span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(dec.action) + '</span>';
      $id('decision-conf').textContent = (dec.confidence * 100).toFixed(0) + '%';
      $id('decision-reason').textContent = dec.reasoning || '';
      $id('decision-provider').textContent = dec.provider || '\u2014';
    }
  } catch (e) {
    console.error(e);
  }
}

/* ── Analyze Stock ── */
var _analyzeTimer = null;

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
    btn.textContent = '\uD83D\uDD0D 诊股';
    return;
  }

  $id('analyze-spinner').style.display = 'block';
  $id('analyze-result').style.display = 'none';

  fetchAuth('/analyze/' + sym, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var html;
      if (d.error) {
        html = '<div class="error-banner" role="alert"><span aria-hidden="true">\u274C</span> ' + escapeHtml(d.error) + '</div>';
      } else {
        var dec = d.decision;
        html = '<div class="result-card">';
        html += '<div style="font-size:18px;font-weight:700;margin-bottom:8px">';
        if (d.name) html += escapeHtml(d.name) + ' ';
        html += '<span style="color:var(--text-secondary);font-size:14px">' + escapeHtml(d.symbol) + '</span>';
        html += '</div>';
        html += '<div class="result-stats">';
        html += '<div class="result-stat"><div>价格</div><div>' + d.price.toFixed(2) + '</div></div>';
        html += '<div class="result-stat"><div>涨跌</div><div class="' + (d.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (d.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + d.change_pct + '%</div></div>';
        html += '<div class="result-stat"><div>RSI</div><div>' + (d.indicators.rsi || '\u2014') + '</div></div>';
        html += '<div class="result-stat"><div>量比</div><div>' + d.indicators.vol_ratio + 'x</div></div>';
        html += '</div>';

        if (d.indicators.macd && d.indicators.macd.dif) {
          html += '<div style="font-size:13px;color:var(--text-secondary)">MACD: DIF=' + d.indicators.macd.dif + ' DEA=' + d.indicators.macd.dea + ' \u67F1=' + d.indicators.macd.histogram + '</div>';
        }
        if (d.trace_signals.length) {
          html += '<div style="font-size:12px;margin-top:6px"><span aria-hidden="true">\uD83D\uDCCA</span> ';
          html += d.trace_signals.map(function(s) {
            return '<span class="' + (s.direction === 'bullish' ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (s.direction === 'bullish' ? '\u2191' : '\u2193') + '</span> ' + escapeHtml(s.type) + '</span>';
          }).join(' ');
          html += '</div>';
        }
        if (dec) {
          html += '<div style="margin-top:12px;padding:12px;background:var(--bg-primary);border-radius:8px">';
          html += '<span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(dec.action) + '</span>';
          html += ' <span style="font-size:13px">置信度 ' + (dec.confidence * 100).toFixed(0) + '%</span>';
          html += '<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(dec.reasoning) + '</div>';
          html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px">AI: ' + escapeHtml(dec.provider) + ' | RAI宏观: ' + d.macro_rai.toFixed(2) + '</div>';
          if (d.data_timestamp) {
            var tsStr = d.data_timestamp.substring(0, 16).replace('T', ' ');
            var isLive = d.data_source === 'akshare' && tsStr.indexOf(new Date().toISOString().substring(0, 10)) >= 0;
            html += '<div style="font-size:10px;color:var(--text-muted);margin-top:2px">\uD83D\uDCC5 数据: ' + escapeHtml(tsStr) + (isLive ? ' <span style="color:var(--color-green)">(\u5B9E\u65F6)</span>' : '') + '</div>';
          }
          html += '</div>';
        }
        html += '</div>';
      }
      $id('analyze-result').innerHTML = html;
      $id('analyze-result').style.display = 'block';

      if (!d.error) {
        $id('kline-chart').classList.remove('chart-container--hidden');
        fetchAuth('/api/kline/' + sym)
          .then(function(r) { return r.json(); })
          .then(function(kd) { Charts.renderKline('kline-chart', kd); })
          .catch(function() { $id('kline-chart').classList.add('chart-container--hidden'); Charts.destroy('kline-chart'); });

        fetchAuth('/risk/position/' + sym + '?price=' + d.price)
          .then(function(r) { return r.json(); })
          .then(function(pos) {
            if (pos && !pos.error && $id('analyze-result').style.display !== 'none') {
              var levelCls = 'pos-level-' + (pos.risk_level || 'normal');
              var box = document.createElement('div');
              box.className = 'position-box';
              box.innerHTML = '<div style="font-size:12px;color:var(--text-muted);margin-bottom:4px">\uD83D\uDCC8 仓位建议</div>' +
                '<span class="pos-level ' + levelCls + '">风控等级: ' + escapeHtml(pos.risk_level || 'normal') + '</span> ' +
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
      }
    })
    .catch(function(e) {
      $id('analyze-result').innerHTML = '<div class="error-banner" role="alert">请求失败: ' + escapeHtml(e.message) + '</div>';
      $id('analyze-result').style.display = 'block';
    })
    .finally(function() {
      $id('analyze-spinner').style.display = 'none';
      _analyzeLoading = false;
      btn.disabled = false;
      btn.textContent = '\uD83D\uDD0D 诊股';
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
    if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }

    var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px"><span aria-hidden="true">\uD83D\uDCCB</span> ' + escapeHtml(d.strategy) + ' — 匹配 ' + d.matched + ' 只</div>';
    d.results.forEach(function(s) {
      var nameDisplay = s.name ? escapeHtml(s.name) + ' ' : '';
      html += '<div class="strat-result" tabindex="0" role="button" aria-label="分析 ' + escapeHtml(s.symbol) + '" onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()}"><span class="price">' + nameDisplay + escapeHtml(s.symbol) + '</span> ' + s.price.toFixed(2) + ' <span class="' + (s.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (s.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + s.change_pct + '%</span> <span style="color:var(--text-secondary)">量比 ' + s.vol_ratio + 'x</span></div>';
    });
    container.innerHTML = html;
  } catch (e) {
    if (e.name === 'AbortError') return;
    container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(e.message) + '</div>';
  }
}

/* ── Tab Switching ── */
function switchTab(tab) {
  _activeTab = tab;
  var buttons = document.querySelectorAll('.tab-btn');
  buttons.forEach(function(b) {
    b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    b.setAttribute('aria-selected', b.getAttribute('data-tab') === tab ? 'true' : 'false');
  });
  var bc = $id('backtest-chart');
  if (bc) bc.style.display = (tab === 'backtest') ? 'block' : 'none';
  loadTab(tab);
}

function loadTab(tab) {
  var panel = $id('tab-panel');
  panel.innerHTML = '<div class="spinner">\u23F3 加载中...</div>';

  if (_tabCache[tab]) {
    panel.innerHTML = _tabCache[tab];
    return;
  }

  var fetchers = {
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
  };

  var fn = fetchers[tab];
  if (!fn) { panel.innerHTML = '<div class="tab-empty">未知面板</div>'; return; }

  fn().then(function(data) {
    var html;
    switch(tab) {
      case 'health':       html = renderHealth(data); break;
      case 'status':       html = renderStatus(data); break;
      case 'reports':      html = renderReportList(data, '宏观报告'); break;
      case 'signal':       html = renderReportList(data, '信号报告'); break;
      case 'trace':        html = renderReportList(data, '资金报告'); break;
      case 'decisions':    html = renderDecisions(data); break;
      case 'risk-history': html = renderRiskHistory(data); break;
      case 'backtest':     html = renderBacktest(data); break;
      default: html = '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
    }
    _tabCache[tab] = html;
    panel.innerHTML = html;
  }).catch(function(e) {
    panel.innerHTML = '<div class="tab-empty">\u26A0\uFE0F 加载失败: ' + escapeHtml(e.message || '网络错误') + '</div>';
  });
}

function renderHealth(d) {
  var html = '<table class="tab-table">';
  html += '<tr><th>系统状态</th><td class="' + (d.status === 'ok' ? 'kv-ok' : 'kv-warn') + '">' + (d.status === 'ok' ? '\u2713' : '\u26A0') + ' ' + escapeHtml(d.status) + '</td></tr>';
  html += '<tr><th>版本</th><td>' + escapeHtml(d.version) + '</td></tr>';
  html += '<tr><th>运行时间</th><td>' + escapeHtml(fmtTime(d.uptime_seconds)) + '</td></tr>';
  html += '<tr><th>Redis</th><td class="' + (d.redis === 'connected' ? 'kv-ok' : 'kv-err') + '">' + escapeHtml(d.redis) + '</td></tr>';
  html += '<tr><th>数据库</th><td class="' + (d.database === 'connected' ? 'kv-ok' : 'kv-err') + '">' + escapeHtml(d.database) + '</td></tr>';
  html += '<tr><th>Agent 运行数</th><td>' + (d.agents_running || 0) + '</td></tr>';
  html += '</table>';
  return html;
}

function renderStatus(d) {
  var html = '<table class="tab-table">';
  html += '<tr><th>运行时间</th><td>' + escapeHtml(fmtTime(d.uptime_seconds)) + '</td></tr>';
  if (d.decision_stats) {
    var s = d.decision_stats;
    html += '<tr><th>决策统计</th><td>共 ' + (s.total || 0) + ' 条';
    if (s.buy) html += ', BUY: ' + s.buy;
    if (s.sell) html += ', SELL: ' + s.sell;
    if (s.hold) html += ', HOLD: ' + s.hold;
    html += '</td></tr>';
  }
  if (d.case_stats && !d.case_stats.error) {
    html += '<tr><th>案例统计</th><td>共 ' + (d.case_stats.total || 0) + ' 条</td></tr>';
  }
  if (d.latest_decision) {
    var ld = d.latest_decision;
    html += '<tr><th>最新决策</th><td>';
    html += '<span class="decision-action action-' + escapeHtml(ld.action) + '">' + escapeHtml(ld.action) + '</span>';
    html += ' 置信度 ' + (ld.confidence * 100).toFixed(0) + '% | ' + escapeHtml(ld.provider);
    html += '<div style="margin-top:6px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(ld.reasoning || '') + '</div>';
    html += '</td></tr>';
  }
  html += '</table>';
  return html;
}

function renderReportList(d, name) {
  var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">' + escapeHtml(name) + ' — 最近 ' + (d.count || 0) + ' 条</div>';
  if (!d.items || !d.items.length) {
    html += '<div class="tab-empty">暂无 ' + escapeHtml(name) + ' 数据</div>';
    return html;
  }
  html += '<table class="tab-table"><tr><th>时间</th><th>代码</th><th>摘要</th><th>置信度</th></tr>';
  d.items.forEach(function(r) {
    var ts = r.timestamp ? new Date(r.timestamp).toLocaleString('zh') : '\u2014';
    html += '<tr><td class="kv-dim">' + escapeHtml(ts) + '</td><td>' + escapeHtml(r.symbol || '\u2014') + '</td><td>' + escapeHtml(r.summary || '\u2014') + '</td><td>' + (r.confidence ? (r.confidence * 100).toFixed(0) + '%' : '\u2014') + '</td></tr>';
  });
  html += '</table>';
  return html;
}

function renderDecisions(d) {
  var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83E\uDDE0 决策历史 — 共 ' + d.count + ' 条';
  if (d.stats) html += ' (BUY: ' + (d.stats.buy || 0) + ', SELL: ' + (d.stats.sell || 0) + ', HOLD: ' + (d.stats.hold || 0) + ')';
  html += '</div>';
  if (!d.items || !d.items.length) {
    html += '<div class="tab-empty">暂无决策记录</div>';
    return html;
  }
  html += '<table class="tab-table"><tr><th>时间</th><th>决策</th><th>置信度</th><th>AI</th><th>理由</th></tr>';
  d.items.forEach(function(dec) {
    var ts = dec.timestamp ? new Date(dec.timestamp).toLocaleString('zh') : '\u2014';
    var did = dec.decision_id ? escapeHtml(dec.decision_id) : '';
    html += '<tr class="decision-row" data-id="' + did + '" onclick="showDecisionModal(\'' + did + '\')" tabindex="0" role="button" aria-label="查看决策详情" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){showDecisionModal(\'' + did + '\')}">';
    html += '<td class="kv-dim">' + escapeHtml(ts) + '</td>';
    html += '<td><span class="decision-action action-' + escapeHtml(dec.action) + '">' + escapeHtml(dec.action) + '</span></td>';
    html += '<td>' + (dec.confidence * 100).toFixed(0) + '%</td>';
    html += '<td class="kv-dim">' + escapeHtml(dec.provider_label || '\u2014') + '</td>';
    html += '<td class="kv-dim">' + escapeHtml((dec.reasoning || '').substring(0, 80)) + '</td>';
    html += '</tr>';
  });
  html += '</table>';
  return html;
}

function renderBacktest(data) {
  var d = data.summary || data;
  var strategies = data.strategies;
  var html = '';

  if (strategies && strategies.strategies) {
    html += _renderStrategyMgmt(strategies.strategies);
  }

  html += '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCCA 股票池 × 7策略回测 — ' + d.count + ' 只股票</div>';
  if (!d.results || !Object.keys(d.results).length) {
    html += '<div class="tab-empty">暂无回测数据（需先刷新缓存生成K线）</div>';
    return html;
  }
  var labels = {breakout: '强势突破', oversold: '超跌反弹', strength: '主力介入', risk: '风险预警', ma_golden_cross: '均线金叉', volume_breakout: '放量突破', rsi_reversal: 'RSI反转'};
  html += '<table class="tab-table"><tr><th>股票</th><th>最优策略</th><th>夏普</th><th>回撤%</th><th>胜率%</th><th>盈亏比</th><th>评分</th></tr>';
  Object.keys(d.results).forEach(function(sym) {
    var best = d.results[sym];
    var top = Object.keys(best)[0];
    if (!top) return;
    var r = best[top];
    var rowClass = r.score > 1 ? 'kv-ok' : r.score > 0 ? '' : 'kv-dim';
    html += '<tr><td><span onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(sym) + '\';analyzeStock()" style="cursor:pointer;font-weight:700;color:var(--accent-blue)">' + escapeHtml(sym) + '</span></td>';
    html += '<td>' + escapeHtml(labels[top] || top) + '</td>';
    html += '<td class="' + (r.sharpe > 0 ? 'kv-ok' : 'kv-dim') + '">' + r.sharpe.toFixed(2) + '</td>';
    html += '<td class="' + (r.max_drawdown_pct < 10 ? 'kv-ok' : 'kv-dim') + '">' + r.max_drawdown_pct + '%</td>';
    html += '<td class="' + (r.win_rate_pct > 50 ? 'kv-ok' : 'kv-dim') + '">' + r.win_rate_pct + '%</td>';
    html += '<td>' + r.profit_factor + '</td>';
    html += '<td class="' + rowClass + '"><strong>' + r.score + '</strong></td>';
    html += '</tr>';
  });
  html += '</table>';

  var strategyScores = {};
  Object.keys(d.results).forEach(function(sym) {
    var strats = d.results[sym];
    Object.keys(strats).forEach(function(name) {
      var s = strats[name];
      if (!strategyScores[name]) strategyScores[name] = { label: labels[name] || name, sharpe: 0, win_rate: 0, count: 0 };
      strategyScores[name].sharpe += s.sharpe || 0;
      strategyScores[name].win_rate += s.win_rate_pct / 100;
      strategyScores[name].count += 1;
    });
  });
  var chartData = [];
  Object.keys(strategyScores).forEach(function(name) {
    var ss = strategyScores[name];
    chartData.push({ label: ss.label, sharpe: ss.count ? ss.sharpe / ss.count : 0, win_rate: ss.count ? ss.win_rate / ss.count : 0 });
  });

  setTimeout(function() {
    var bc = document.getElementById('backtest-chart');
    if (bc) {
      bc.style.display = 'block';
      Charts.renderBacktestBars('backtest-chart', chartData);
    }
  }, 100);

  return html;
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
  html += '<table class="tab-table"><tr><th>时间</th><th>级别</th><th>规则</th><th>股票</th><th>详情</th></tr>';
  items.forEach(function(ev) {
    var ts = ev.timestamp ? new Date(ev.timestamp).toLocaleString('zh') : '\u2014';
    var levelCls = ev.level === 'critical' ? 'kv-err' : ev.level === 'elevated' ? 'kv-warn' : '';
    html += '<tr>';
    html += '<td class="kv-dim">' + escapeHtml(ts) + '</td>';
    html += '<td class="' + levelCls + '"><strong>' + escapeHtml(ev.level || '\u2014') + '</strong></td>';
    html += '<td>' + escapeHtml(ev.rule || '\u2014') + '</td>';
    html += '<td>' + escapeHtml(ev.symbol || '\u2014') + '</td>';
    html += '<td class="kv-dim">' + escapeHtml((ev.detail || '').substring(0, 80)) + '</td>';
    html += '</tr>';
  });
  html += '</table>';
  return html;
}

function _renderStrategyMgmt(strategies) {
  var html = '<div class="strat-mgmt">';
  html += '<div class="strat-mgmt-header"><h3>\u2699\uFE0F 策略管理</h3>';
  html += '<button class="strat-btn" onclick="runManualBacktest()" style="font-size:12px;padding:6px 12px">\uD83D\uDD04 手动回测</button>';
  html += '</div>';
  html += '<table class="tab-table" style="font-size:13px"><tr><th>策略</th><th>状态</th><th>连续失败</th><th>上次评分</th><th>操作</th></tr>';
  var labels = {breakout: '强势突破', oversold: '超跌反弹', strength: '主力介入', risk: '风险预警', ma_golden_cross: '均线金叉', volume_breakout: '放量突破', rsi_reversal: 'RSI反转'};
  strategies.forEach(function(s) {
    var active = s.status === 'active';
    var scoreStr = s.last_score != null ? s.last_score.toFixed(2) : '\u2014';
    html += '<tr>';
    html += '<td>' + escapeHtml(labels[s.name] || s.name) + '</td>';
    html += '<td class="' + (active ? 'kv-ok' : 'kv-err') + '">' + (active ? '\u2713 活跃' : '\u2717 禁用') + '</td>';
    html += '<td class="' + (s.consecutive_losses > 3 ? 'kv-err' : '') + '">' + (s.consecutive_losses || 0) + '</td>';
    html += '<td>' + scoreStr + '</td>';
    html += '<td>' + (active ? '<span style="color:var(--text-muted);font-size:12px">运行中</span>' : '<button class="toggle-btn toggle-btn-enable" onclick="event.stopPropagation();enableStrategy(\'' + escapeHtml(s.name) + '\')">\u25B6 启用</button>') + '</td>';
    html += '</tr>';
  });
  html += '</table></div>';
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

/* ── Risk history click on card ── */
$id('risk-level-display').parentElement.addEventListener('click', function() {
  switchTab('risk-history');
});
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
      html += '<div class="modal-section"><div class="modal-label">决策</div><div class="modal-value"><span class="decision-action action-' + escapeHtml(d.action) + '">' + escapeHtml(d.action) + '</span> 置信度 ' + (d.confidence * 100).toFixed(0) + '%</div></div>';
      html += '<div class="modal-section"><div class="modal-label">AI 模型</div><div class="modal-value">' + escapeHtml(d.provider_label || '\u2014') + ' (' + escapeHtml(d.provider_status || '\u2014') + ')</div></div>';
      html += '<div class="modal-section"><div class="modal-label">时间</div><div class="modal-value">' + escapeHtml(d.timestamp ? new Date(d.timestamp).toLocaleString('zh') : '\u2014') + '</div></div>';
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

$id('decision-modal').addEventListener('click', function(e) {
  if (e.target === this) closeDecisionModal();
});

/* ── Watchlist ── */
function refreshWatchlist() {
  var btn = $id('watchlist-refresh-btn');
  btn.disabled = true;
  btn.textContent = '\u23F3';
  $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">刷新中...</div>';

  fetchAuth('/watchlist')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(wl) {
      if (wl && wl.items) {
        var wlHtml = '';
        if (wl.items.length === 0) {
          wlHtml = '<div style="color:var(--text-muted);font-size:13px">暂无持仓</div>';
        } else {
          wl.items.forEach(function(item) {
            var changeCls = item.change_pct != null ? (item.change_pct >= 0 ? 'trend-up' : 'trend-down') : '';
            var changeStr = item.change_pct != null ? '<span class="' + changeCls + '"><span aria-hidden="true">' + (item.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + item.change_pct.toFixed(2) + '%</span>' : '\u2014';
            var priceStr = item.price != null ? item.price.toFixed(2) : '\u2014';
            var nameStr = item.name || '';
            var displayName = nameStr ? escapeHtml(nameStr) + ' <span style="color:var(--text-secondary);font-size:11px">' + escapeHtml(item.symbol) + '</span>' : escapeHtml(item.symbol);
            wlHtml += '<div class="wl-row" style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg-tag);font-size:13px">';
            wlHtml += '<span style="cursor:pointer;flex:1" onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(item.symbol) + '\';analyzeStock()" title="点击诊股">' + displayName + '</span>';
            wlHtml += '<span style="margin:0 8px">' + priceStr + '</span>';
            wlHtml += '<span style="margin:0 8px;min-width:60px;text-align:right">' + changeStr + '</span>';
            wlHtml += '<button onclick="event.stopPropagation();removeFromWatchlist(\'' + escapeHtml(item.symbol) + '\')" style="background:none;border:none;color:var(--color-red);cursor:pointer;font-size:16px;padding:0 4px" title="移除" aria-label="移除 ' + escapeHtml(item.symbol) + '">\u00D7</button>';
            wlHtml += '</div>';
          });
        }
        $id('watchlist-items').innerHTML = wlHtml;
      } else {
        $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">加载失败</div>';
      }
    })
    .catch(function() {
      $id('watchlist-items').innerHTML = '<div style="color:var(--text-muted);font-size:13px">加载失败</div>';
    })
    .finally(function() {
      btn.disabled = false;
      btn.textContent = '\u21BB';
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
    .finally(function() { btn.disabled = false; btn.textContent = '+ \u6DFB\u52A0'; });
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

$id('watchlist-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') addToWatchlist();
});

$id('stock-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') analyzeStock();
});

switchTab('health');
startPoll();
