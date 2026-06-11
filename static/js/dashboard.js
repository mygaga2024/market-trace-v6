/* ──────────────────────────────────────
   Market Trace V6.0 — Dashboard Logic
   ────────────────────────────────────── */

// 全局异常捕获
window.addEventListener('error', function(e) {
  var msg = '[JS Error] ' + (e.message || '未知错误') + ' @ ' + (e.filename || '').split('/').pop() + ':' + (e.lineno || '?');
  console.error(msg, e.error);
  var el = document.createElement('div');
  el.className = 'toast toast-error';
  el.setAttribute('role', 'alert');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(function() { el.remove(); }, 8000);
});
window.addEventListener('unhandledrejection', function(e) {
  var msg = '[Promise Error] ' + (e.reason && e.reason.message || '未知错误');
  console.error(msg, e.reason);
  var el = document.createElement('div');
  el.className = 'toast toast-error';
  el.setAttribute('role', 'alert');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(function() { el.remove(); }, 8000);
});

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
      $id('risk-override-count').textContent = rk.daily_overrides || 0;
      $id('risk-event-count').textContent = rk.total_overrides || 0;
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
  $id('analyze-spinner').scrollIntoView({ behavior: 'smooth', block: 'start' });

  fetchAuth('/analyze/' + sym, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var html;
      if (d.error) {
        html = '<div class="error-banner" role="alert"><span aria-hidden="true">\u274C</span> ' + escapeHtml(d.error) + '</div>';
      } else {
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
        html += '<div class="result-stat"><div>价格</div><div>' + d.price.toFixed(2) + '</div></div>';
        html += '<div class="result-stat"><div>涨跌</div><div class="' + (d.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (d.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + d.change_pct + '%</div></div>';
        html += '<div class="result-stat"><div>RSI</div><div>' + (ind.rsi || '\u2014') + '</div></div>';
        html += '<div class="result-stat"><div>量比</div><div>' + (ind.vol_ratio || 0) + 'x</div></div>';
        html += '<div class="result-stat"><div>ATR</div><div>' + (ind.atr ? ind.atr.toFixed(2) : '\u2014') + '</div></div>';
        html += '</div>';

        // 均线
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

        // 策略命中
        if (d.strategy_hits && d.strategy_hits.length) {
          html += '<div style="font-size:12px;margin-top:4px"><span aria-hidden="true">\uD83C\uDFAF</span> 策略命中: ';
          html += d.strategy_hits.map(function(s) {
            return '<span class="' + (s.type === 'BUY' ? 'trend-up' : 'trend-down') + '" style="margin-right:6px">' + escapeHtml(s.label) + '</span>';
          }).join('');
          html += '</div>';
        }

        if (d.trace_signals.length) {
          html += '<div style="font-size:12px;margin-top:4px"><span aria-hidden="true">\uD83D\uDCCA</span> ';
          html += d.trace_signals.map(function(s) {
            return '<span class="' + (s.direction === 'bullish' ? 'trend-up' : 'trend-down') + '" style="margin-right:6px">' + (s.direction === 'bullish' ? '\u2191' : '\u2193') + ' ' + escapeHtml(s.type) + '</span>';
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
        $id('analyze-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    })
    .catch(function(e) {
      $id('analyze-result').innerHTML = '<div class="error-banner" role="alert">请求失败: ' + escapeHtml(e.message) + '</div>';
      $id('analyze-result').style.display = 'block';
      $id('analyze-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    renderScreenResults(container, d);
  } catch (e) {
    if (e.name === 'AbortError') return;
    container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(e.message) + '</div>';
  }
}

function renderScreenResults(container, d) {
  var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px"><span aria-hidden="true">\uD83D\uDCCB</span> ' + escapeHtml(d.strategy) + ' — 匹配 ' + d.matched + ' 只</div>';
  d.results.forEach(function(s) {
    var nameDisplay = s.name ? escapeHtml(s.name) + ' ' : '';
    html += '<div class="strat-result" tabindex="0" onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()"><span class="price">' + nameDisplay + escapeHtml(s.symbol) + '</span> ' + s.price.toFixed(2) + ' <span class="' + (s.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (s.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + s.change_pct + '%</span> <span style="color:var(--text-secondary)">量比 ' + s.vol_ratio + 'x</span></div>';
  });
  container.innerHTML = html;
}

/* ── 全市场扫描 ── */
function fullScan(strategy) {
  var container = $id('fullscan-results');
  container.style.display = 'block';
  container.innerHTML = '<div class="spinner" role="status">\u23F3 全市场扫描中... 正在扫描5000+只A股，预计30-60秒</div>';

  fetchAuth('/scan/' + strategy, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }
      var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">';
      html += '\uD83D\uDD0D ' + escapeHtml(d.strategy) + ' — 全市场扫描';
      html += ' | 总计' + d.total_stocks + '只 | 检查' + d.checked + '只 | 命中<strong>' + d.matched + '</strong>只';
      html += ' | 耗时' + d.elapsed_seconds + 's';
      html += '</div>';
      if (d.results && d.results.length) {
        html += '<table class="tab-table"><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>量比</th><th>操作</th></tr>';
        d.results.forEach(function(s) {
          var cls = s.change_pct >= 0 ? 'trend-up' : 'trend-down';
          html += '<tr><td>' + escapeHtml(s.symbol) + '</td><td>' + escapeHtml(s.name || '') + '</td><td>' + s.price.toFixed(2) + '</td><td class="' + cls + '">' + (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%</td><td>' + s.vol_ratio.toFixed(1) + 'x</td>';
          html += '<td><button onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()" style="padding:2px 8px;background:var(--btn-primary-bg);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">诊股</button></td></tr>';
        });
        html += '</table>';
      } else {
        html += '<div class="tab-empty">未命中任何股票</div>';
      }
      container.innerHTML = html;
    })
    .catch(function(e) {
      container.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F ' + escapeHtml(e.message) + '</div>';
    });
}

function smartScan() {
  var container = $id('fullscan-results');
  container.style.display = 'block';
  container.innerHTML = '<div class="spinner" role="status">\u23F3 智能扫描中... 7策略×5000+只A股，预计60-90秒</div>';

  fetchAuth('/scan/smart', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(d.error) + '</div>'; return; }
      var html = '<div style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">';
      html += '\uD83E\uDDE0 智能综合扫描 — 全市场7策略评分';
      html += ' | 总计' + d.total + '只 | 命中' + d.scored + '只 | 耗时' + d.elapsed_seconds + 's';
      html += '</div>';
      if (d.results && d.results.length) {
        html += '<table class="tab-table"><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌</th><th>最优策略</th><th>评分</th><th>操作</th></tr>';
        d.results.forEach(function(s) {
          var cls = s.change_pct >= 0 ? 'trend-up' : 'trend-down';
          html += '<tr><td>' + escapeHtml(s.symbol) + '</td><td>' + escapeHtml(s.name || '') + '</td><td>' + s.price.toFixed(2) + '</td><td class="' + cls + '">' + (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%</td>';
          html += '<td>' + escapeHtml(s.strategy_label || s.strategy) + '</td><td><strong>' + s.score.toFixed(1) + '</strong></td>';
          html += '<td><button onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()" style="padding:2px 8px;background:var(--btn-primary-bg);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">诊股</button></td></tr>';
        });
        html += '</table>';
      } else {
        html += '<div class="tab-empty">未命中任何股票</div>';
      }
      container.innerHTML = html;
    })
    .catch(function(e) {
      container.innerHTML = '<div class="error-banner" role="alert">\u26A0\uFE0F ' + escapeHtml(e.message) + '</div>';
    });
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
    logs:         function() { return fetchAuth('/logs?lines=100').then(function(r) { return r.json(); }); },
    paper:        function() { return fetchAuth('/paper/account').then(function(r) { return r.json(); }); },
    help:         function() { return Promise.resolve({}); },
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
      case 'logs':         html = renderLogs(data); break;
      case 'paper':        html = renderPaper(data); break;
      case 'help':         html = renderHelp(); break;
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
  if (d.stats) { var ad = d.stats.action_distribution || {}; html += ' (BUY: ' + (ad.BUY || 0) + ', SELL: ' + (ad.SELL || 0) + ', HOLD: ' + (ad.HOLD || 0) + ')'; }
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
    var stratArr = Object.entries(strategies.strategies).map(function(e) { e[1].name = e[0]; return e[1]; });
    html += _renderStrategyMgmt(stratArr);
  }

  html += '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCCA 股票池 × 7策略回测 — ' + d.count + ' 笔结果</div>';
  if (!d.results || !Object.keys(d.results).length) {
    html += '<div class="tab-empty">暂无回测数据（需先刷新缓存生成K线）</div>';
    return html;
  }
  var labels = {breakout: '强势突破', oversold: '超跌反弹', strength: '主力介入', risk: '风险预警', ma_golden_cross: '均线金叉', volume_breakout: '放量突破', rsi_reversal: 'RSI反转'};
  html += '<table class="tab-table"><tr><th>股票</th><th>最优策略</th><th>夏普</th><th>索提诺</th><th>回撤%</th><th>胜率%</th><th>盈亏比</th><th>Alpha</th><th>评分</th></tr>';
  Object.keys(d.results).forEach(function(sym) {
    var best = d.results[sym];
    var top = Object.keys(best)[0];
    if (!top) return;
    var r = best[top];
    var rowClass = r.score > 1 ? 'kv-ok' : r.score > 0 ? '' : 'kv-dim';
    var shrp = r.sharpe_ratio || r.sharpe || 0;
    html += '<tr style="cursor:pointer" onclick="showBacktestDetail(\'' + escapeHtml(sym) + '\')" title="点击查看详情">';
    html += '<td><span style="font-weight:700;color:var(--accent-blue)">' + escapeHtml(sym) + '</span></td>';
    html += '<td>' + escapeHtml(labels[r.strategy] || labels[top] || top) + '</td>';
    html += '<td class="' + (shrp > 0 ? 'kv-ok' : 'kv-dim') + '">' + shrp.toFixed(2) + '</td>';
    html += '<td class="' + ((r.sortino_ratio || 0) > 0 ? 'kv-ok' : 'kv-dim') + '">' + (r.sortino_ratio || 0).toFixed(2) + '</td>';
    html += '<td class="' + (r.max_drawdown_pct < 10 ? 'kv-ok' : 'kv-dim') + '">' + r.max_drawdown_pct + '%</td>';
    html += '<td class="' + (r.win_rate_pct > 50 ? 'kv-ok' : 'kv-dim') + '">' + r.win_rate_pct + '%</td>';
    html += '<td>' + r.profit_factor + '</td>';
    html += '<td class="' + ((r.alpha || 0) > 0 ? 'kv-ok' : 'kv-dim') + '">' + (r.alpha || 0).toFixed(2) + '%</td>';
    html += '<td class="' + rowClass + '"><strong>' + r.score + '</strong></td>';
    html += '</tr>';
  });
  html += '</table>';

  // 策略综合对比
  var strategyScores = {};
  Object.keys(d.results).forEach(function(sym) {
    var strats = d.results[sym];
    Object.keys(strats).forEach(function(name) {
      var s = strats[name];
      var shrp = s.sharpe_ratio || s.sharpe || 0;
      if (!strategyScores[name]) strategyScores[name] = { label: labels[name] || name, sharpe: 0, win_rate: 0, count: 0 };
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
  setTimeout(function() {
    var bc = document.getElementById('backtest-chart');
    if (bc) {
      bc.style.display = 'block';
      Charts.renderBacktestBars('backtest-chart', chartData);
    }
  }, 100);

  return html;
}

// 股票回测详情（权益曲线）
var _btDetailSym = null;
function showBacktestDetail(symbol) {
  if (_btDetailSym === symbol) {
    document.getElementById('backtest-detail').style.display = 'none';
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
        container.style.cssText = 'margin-top:16px;padding:16px;background:var(--bg-card);border:1px solid var(--border-color);border-radius:12px';
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

      setTimeout(function() {
        Charts.renderEquityCurve('backtest-equity-chart', 'backtest-dd-chart', r.equity_curve, r.benchmark_curve, r.drawdown_curve, r.trade_markers);
      }, 100);
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
  html += '<table class="tab-table"><tr><th>时间</th><th>级别</th><th>规则</th><th>股票</th><th>详情</th></tr>';
  items.forEach(function(ev) {
    var ts = ev.timestamp ? new Date(ev.timestamp).toLocaleString('zh') : '\u2014';
    var levelCls = ev.severity === 'critical' ? 'kv-err' : ev.severity === 'elevated' ? 'kv-warn' : '';
    html += '<tr>';
    html += '<td class="kv-dim">' + escapeHtml(ts) + '</td>';
    html += '<td class="' + levelCls + '"><strong>' + escapeHtml(ev.severity || '\u2014') + '</strong></td>';
    html += '<td>' + escapeHtml(ev.reason || '\u2014') + '</td>';
    html += '<td>' + escapeHtml(ev.symbol || '\u2014') + '</td>';
    html += '<td class="kv-dim">' + escapeHtml((ev.action || '').substring(0, 80)) + '</td>';
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

function renderPaper(d) {
  if (!d || d.error) {
    return '<div class="tab-empty">\u26A0\uFE0F ' + escapeHtml(d && d.error || '加载失败') + '</div>';
  }
  var html = '<div style="margin-bottom:8px;font-size:13px;color:var(--text-secondary)">\uD83D\uDCB0 纸上交易账户 — ' + escapeHtml(d.account_id || 'default') + '</div>';
  var pnlCls = d.total_pnl_pct >= 0 ? 'trend-up' : 'trend-down';
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
    html += '<table class="tab-table"><tr><th>代码</th><th>数量</th><th>均价</th><th>成本</th></tr>';
    d.positions.forEach(function(p) {
      html += '<tr><td>' + escapeHtml(p.symbol) + '</td><td>' + p.quantity + '</td><td>' + p.avg_cost + '</td><td>' + (p.cost_basis || 0).toLocaleString() + '</td></tr>';
    });
    html += '</table>';
  }

  if (d.recent_orders && d.recent_orders.length) {
    html += '<h3 class="card-title" style="margin-top:12px">\uD83D\uDCCB 最近交易</h3>';
    html += '<table class="tab-table"><tr><th>时间</th><th>代码</th><th>方向</th><th>数量</th><th>价格</th><th>理由</th></tr>';
    d.recent_orders.slice(-10).reverse().forEach(function(o) {
      var actCls = o.action === 'BUY' ? 'trend-up' : 'trend-down';
      html += '<tr><td class="kv-dim">' + escapeHtml(new Date(o.timestamp).toLocaleString('zh')) + '</td><td>' + escapeHtml(o.symbol) + '</td><td class="' + actCls + '">' + o.action + '</td><td>' + o.quantity + '</td><td>' + o.price + '</td><td class="kv-dim">' + escapeHtml((o.reason || '').substring(0, 40)) + '</td></tr>';
    });
    html += '</table>';
  } else {
    html += '<div class="tab-empty">暂无交易 — 执行AI诊股后将自动记录纸上交易</div>';
  }
  return html;
}

function renderHelp() {
  return '\
<div class="help-guide">\
<h2>&#x2753; Market Trace V6.0 使用指南</h2>\
\
<h3>&#x1F3AF; 诊股</h3>\
<p>在顶部输入框输入股票代码（如 <code>000001</code>），点击<strong>"诊股"</strong>按钮或按回车。</p>\
<p>系统将拉取K线数据，计算14项技术指标（RSI/MACD/布林带/KDJ/ATR/支撑阻力/均线趋势），检测7策略信号，并通过AI三级回退链（DeepSeek→Gemini→MiniMax→纯规则）输出交易决策。</p>\
\
<h3>&#x1F4BC; 持仓列表</h3>\
<p>添加关注的股票代码，系统自动显示实时价格和涨跌幅。点击股票名称可快速诊股，点击 <strong>&#x00D7;</strong> 可移除。右上角<strong>"刷新列表"</strong>按钮可手动刷新所有持仓价格。</p>\
\
<h3>&#x1F4CA; 策略回测</h3>\
<p>选择"策略回测"Tab，查看股票池×7策略的回测结果。表格展示夏普比率、索提诺比率、最大回撤、胜率、Alpha/Beta等指标。<strong>点击股票行</strong>可查看权益曲线、回撤曲线和买卖标记。</p>\
<p>点击<strong>"手动回测"</strong>按钮可触发新一轮回测。策略评分不足时会警告但不会自动禁用。</p>\
\
<h3>&#x1F50D; 全市场扫描（选股）</h3>\
<p>页面底部<strong>"全市场扫描"</strong>区域：</p>\
<ul>\
<li><strong>绿色按钮</strong> — 对5526只A股做单策略批量筛选。先按实时涨跌幅粗筛，再对有缓存K线的股票做深度策略验证。</li>\
<li><strong>紫色"智能综合"按钮</strong> — 对全部有缓存K线的股票跑7策略综合评分排行。</li>\
<li>扫描结果可直接点<strong>"诊股"</strong>按钮跳转详细分析。</li>\
</ul>\
<p>上方<strong>"股票池扫描"</strong>仅对配置的stock_pool做策略筛选。</p>\
\
<h3>&#x1F4B0; 纸上交易</h3>\
<p>每次AI诊股后，系统自动在模拟账户中执行一笔纸上交易。查看<strong>"纸上交易"Tab</strong>可追踪模拟账户的权益变化、持仓和交易记录。</p>\
<p>点击<strong>"按市价估值"</strong>可更新所有纸上持仓的当前市值。</p>\
\
<h3>&#x1F6E1; 风控闭环</h3>\
<p>Risk Agent 实时监控宏观RAI和资金流向。当RAI极端值(>0.75或<0.25)与资金方向矛盾时，自动降权AI决策置信度。风控历史Tab记录所有否决事件。</p>\
\
<h3>&#x1F4DC; 系统日志</h3>\
<p>查看最近100行系统日志，用于排查异常或了解系统运行状态。</p>\
\
<h3>&#x26A1; 快捷操作</h3>\
<ul>\
<li>持仓列表中<strong>点击股票名称</strong> → 快速诊股</li>\
<li>回测表格中<strong>点击股票行</strong> → 查看权益曲线</li>\
<li>扫描结果中<strong>点击"诊股"</strong> → 跳转分析</li>\
<li>风控卡片<strong>点击</strong> → 跳转风控历史</li>\
<li>决策历史中<strong>点击行</strong> → 查看完整决策详情</li>\
</ul>\
\
<h3>&#x1F4E1; AI决策链</h3>\
<p>系统使用三级LLM回退链确保决策不中断：<strong>DeepSeek → Gemini → MiniMax → 纯规则加权</strong>。任一环节熔断或超时自动降级到下一级。</p>\
\
<h3>&#x1F4CA; 技术指标说明</h3>\
<table class="tab-table">\
<tr><th>指标</th><th>说明</th></tr>\
<tr><td>RSI</td><td>相对强弱指数，>70超买(看空)，<30超卖(看多)</td></tr>\
<tr><td>MACD</td><td>异同移动均线，金叉看多，死叉看空</td></tr>\
<tr><td>布林带</td><td>价格在上下轨间波动，带宽收窄预示变盘</td></tr>\
<tr><td>KDJ</td><td>随机指标，J>100超买，J<0超卖</td></tr>\
<tr><td>ATR</td><td>平均真实波幅，衡量波动率</td></tr>\
<tr><td>RAI</td><td>风险偏好指数，0-1，>0.55乐观，<0.45悲观</td></tr>\
<tr><td>Alpha</td><td>策略超额收益(相对基准)</td></tr>\
<tr><td>Beta</td><td>系统性风险暴露(相对基准)</td></tr>\
<tr><td>Sharpe</td><td>风险调整后收益，>1良好</td></tr>\
<tr><td>Sortino</td><td>下行风险调整收益，>2优秀</td></tr>\
</table>\
</div>\
<style>\
.help-guide { max-width:800px; line-height:1.8; }\
.help-guide h2 { font-size:20px; margin-bottom:16px; color:var(--accent-blue); }\
.help-guide h3 { font-size:15px; margin-top:20px; margin-bottom:8px; color:var(--text-primary); border-bottom:1px solid var(--bg-tag); padding-bottom:4px; }\
.help-guide p { font-size:14px; color:var(--text-secondary); margin-bottom:8px; }\
.help-guide ul { color:var(--text-secondary); font-size:14px; padding-left:20px; margin-bottom:8px; }\
.help-guide li { margin-bottom:4px; }\
.help-guide code { background:var(--bg-tag); padding:2px 6px; border-radius:4px; font-size:13px; }\
.help-guide strong { color:var(--text-primary); }\
</style>\
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
