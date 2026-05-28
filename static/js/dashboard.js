/* ──────────────────────────────────────
   Market Trace V6.0 — Dashboard Logic
   ────────────────────────────────────── */

const API_TOKEN = window.__API_TOKEN__ || '';

function fetchAuth(url, options = {}) {
  opts = { ...options };
  if (API_TOKEN) {
    opts.headers = { ...(opts.headers || {}), 'Authorization': 'Bearer ' + API_TOKEN };
  }
  return fetchWithRetry(url, opts);
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
      fetchAuth('/health').then(function(r) { return r.json(); }).catch(function() { return null; }),
      fetchAuth('/status').then(function(r) { return r.json(); }).catch(function() { return null; }),
      fetchAuth('/reports/macro/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      fetchAuth('/reports/signal/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
      fetchAuth('/reports/trace/latest').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    ]);

    var h = results[0], st = results[1], mr = results[2], lr = results[3], dr = results[4];

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
          html += '</div>';
        }
        html += '</div>';
      }
      $id('analyze-result').innerHTML = html;
      $id('analyze-result').style.display = 'block';
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
      html += '<div class="strat-result" tabindex="0" role="button" aria-label="分析 ' + escapeHtml(s.symbol) + '" onclick="document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){document.getElementById(\'stock-input\').value=\'' + escapeHtml(s.symbol) + '\';analyzeStock()}"><span class="price">' + escapeHtml(s.symbol) + '</span> ' + s.price.toFixed(2) + ' <span class="' + (s.change_pct >= 0 ? 'trend-up' : 'trend-down') + '"><span aria-hidden="true">' + (s.change_pct >= 0 ? '\u2191' : '\u2193') + '</span> ' + s.change_pct + '%</span> <span style="color:var(--text-secondary)">量比 ' + s.vol_ratio + 'x</span></div>';
    });
    container.innerHTML = html;
  } catch (e) {
    if (e.name === 'AbortError') return;
    container.innerHTML = '<div class="error-banner" role="alert">' + escapeHtml(e.message) + '</div>';
  }
}

/* ── Keyboard Submit ── */
$id('stock-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') analyzeStock();
});

startPoll();
