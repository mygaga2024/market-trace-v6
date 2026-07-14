/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Backtest
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;

  function _barPct(val, max, color) {
    var pct = max > 0 ? Math.min(100, Math.abs(val) / max * 100) : 0;
    return '<div style="display:flex;align-items:center;gap:6px"><span>' + (val != null ? (val >= 0 ? '+' : '') + val.toFixed(2) + '%' : '\u2014') + '</span><div style="flex:1;height:4px;background:var(--bg-tag);border-radius:2px"><div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:2px"></div></div></div>';
  }

  function renderBacktest(data) {
    var summary = data && data.summary ? data.summary : data;
    var results = summary && summary.results ? summary.results : {};
    var strategies = data && data.strategies ? data.strategies : null;
    var h = '';

    if (strategies && strategies.strategies) {
      h += '<div class="tab-section"><h3 class="tab-section-title">策略状态</h3><table class="status-table"><thead><tr><th>策略</th><th>状态</th><th>连续失败</th><th>评分</th><th>操作</th></tr></thead><tbody>';
      Object.keys(strategies.strategies).forEach(function(name) {
        var s = strategies.strategies[name];
        var statusCls = s.status === 'active' ? 'badge-ok' : 'badge-warn';
        h += '<tr><td style="font-weight:600">' + E(s.label || name) + '</td><td><span class="badge ' + statusCls + '">' + (s.status === 'active' ? '活跃' : '禁用') + '</span></td>';
        h += '<td>' + (s.consecutive_losses || 0) + '</td><td>' + (s.last_score != null ? s.last_score.toFixed(2) : '\u2014') + '</td>';
        h += '<td>' + (s.status !== 'active' ? '<button onclick="window._DS.enableStrat(\'' + E(name) + '\')" class="strat-btn strat-btn-primary" style="font-size:12px;padding:2px 8px">启用</button>' : '<span style="color:var(--text-muted);font-size:12px">—</span>') + '</td></tr>';
      });
      h += '</tbody></table><button onclick="window._DS.runBT()" class="strat-btn strat-btn-primary" style="margin-top:10px">触发手动回测</button></div>';
    }

    var symbols = Object.keys(results);
    if (!symbols.length) return h + '<div class="tab-empty">暂无回测结果，请先执行手动回测</div>';

    var allReturns = [];
    symbols.forEach(function(sym) {
      Object.keys(results[sym]).forEach(function(strat) { allReturns.push(Math.abs(results[sym][strat].total_return_pct)); });
    });
    var maxRet = Math.max.apply(null, allReturns.length ? allReturns : [1]);

    h += '<div class="tab-section"><h3 class="tab-section-title">回测结果 (' + (summary.count || symbols.length) + ')</h3>';
    h += '<table class="status-table" style="font-size:13px"><thead><tr><th>股票</th><th>策略</th><th>夏普</th><th>胜率</th><th>总收益</th><th>最大回撤</th><th style="width:60px">交易</th></tr></thead><tbody>';
    symbols.forEach(function(sym) {
      Object.keys(results[sym]).forEach(function(strat) {
        var r = results[sym][strat];
        var retCls = r.total_return_pct >= 0 ? 'trend-up' : 'trend-down';
        var sharpeCls = r.sharpe_ratio >= 1 ? 'trend-up' : (r.sharpe_ratio <= 0 ? 'trend-down' : '');
        h += '<tr style="cursor:pointer" onclick="window._DS.btDetail(\'' + E(sym) + '\')">';
        h += '<td style="font-weight:600">' + E(sym) + '</td><td>' + E(r.strategy_label || strat) + '</td>';
        h += '<td class="' + sharpeCls + '" style="font-variant-numeric:tabular-nums">' + (r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '\u2014') + '</td>';
        h += '<td style="font-variant-numeric:tabular-nums">' + (r.win_rate_pct != null ? r.win_rate_pct.toFixed(1) + '%' : '\u2014') + '</td>';
        h += '<td class="' + retCls + '" style="font-variant-numeric:tabular-nums">' + _barPct(r.total_return_pct, maxRet, r.total_return_pct >= 0 ? 'var(--color-rise)' : 'var(--color-fall)') + '</td>';
        h += '<td style="font-variant-numeric:tabular-nums">' + (r.max_drawdown_pct != null ? r.max_drawdown_pct.toFixed(2) + '%' : '\u2014') + '</td>';
        h += '<td style="text-align:center">' + (r.total_trades || 0) + '</td></tr>';
      });
    });
    h += '</tbody></table></div>';

    return h;
  }

  function showBacktestDetail(symbol) {
    var modal = document.getElementById('decision-modal'), body = document.getElementById('decision-modal-body');
    if (!modal || !body) return;
    modal.style.display = 'flex';
    body.innerHTML = '<div class="spinner">加载中...</div>';
    S.fetchAuth('/backtest/rolling/' + symbol).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { body.innerHTML = '<div class="error-banner">' + E(d.error) + '</div>'; return; }
      var h = '<h3>' + E(symbol) + ' 滚动回测 <span style="font-weight:400;color:var(--text-muted);font-size:14px">' + E(d.label || d.strategy) + '</span></h3>';
      h += '<table class="status-table"><tbody>';
      h += '<tr><td style="width:80px">训练集</td><td>' + d.train_bars + ' 条</td></tr>';
      h += '<tr><td>测试集</td><td>' + (d.test_bars || 0) + ' 条</td></tr>';
      h += '<tr><td>测试窗口</td><td>' + (d.total_windows || 0) + ' 个</td></tr>';
      h += '<tr><td>平均胜率</td><td>' + (d.avg_win_rate || 0) + '%</td></tr>';
      h += '<tr><td>平均夏普</td><td>' + (d.avg_sharpe || 0) + '</td></tr>';
      h += '<tr><td>平均收益</td><td>' + (d.avg_return || 0) + '%</td></tr>';
      h += '<tr><td>一致性</td><td>' + ((d.consistency || 0) * 100).toFixed(0) + '%</td></tr>';
      h += '<tr><td>最佳参数</td><td style="font-size:12px;color:var(--text-secondary)">' + E(JSON.stringify(d.best_params || {})) + '</td></tr>';
      h += '</tbody></table>';
      body.innerHTML = h;
    }).catch(function(e) { body.innerHTML = '<div class="error-banner">加载失败: ' + E(e.message) + '</div>'; });
  }

  function runManualBacktest() {
    S.fetchAuth('/backtest/run', { method: 'POST' }).then(function(r) { return r.json(); }).then(function(d) {
      S.showToast(d.error ? d.error : '回测完成: ' + (d.count || 0) + ' 条结果', d.error ? 'error' : 'success');
      S.loadTab('backtest');
    }).catch(function(e) { S.showToast('回测失败: ' + (e.message || '网络错误'), 'error'); });
  }

  function enableStrategy(name) {
    S.fetchAuth('/backtest/strategies/' + name + '/enable', { method: 'POST' }).then(function(r) { return r.json(); }).then(function() {
      S.showToast('策略 ' + name + ' 已启用', 'success');
      S.loadTab('backtest');
    }).catch(function(e) { S.showToast('启用失败: ' + (e.message || '网络错误'), 'error'); });
  }

  window.TAB_BACKTEST = { renderBacktest: renderBacktest, showBacktestDetail: showBacktestDetail, runManualBacktest: runManualBacktest, enableStrategy: enableStrategy };
})();
