/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Backtest
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;

  function renderBacktest(data) {
    var summary = data && data.summary ? data.summary : data;
    var results = summary && summary.results ? summary.results : {};
    var strategies = data && data.strategies ? data.strategies : null;

    var h = '';
    if (strategies && strategies.strategies) {
      h += '<h3>策略状态</h3><table class="status-table"><thead><tr><th>策略</th><th>状态</th><th>连续失败</th><th>评分</th><th>操作</th></tr></thead><tbody>';
      Object.keys(strategies.strategies).forEach(function(name) {
        var s = strategies.strategies[name];
        var statusCls = s.status === 'active' ? 'badge-ok' : 'badge-warn';
        h += '<tr><td>' + E(s.label || name) + '</td><td><span class="badge ' + statusCls + '">' + E(s.status || '') + '</span></td>';
        h += '<td>' + (s.consecutive_losses || 0) + '</td><td>' + (s.last_score != null ? s.last_score.toFixed(2) : '\u2014') + '</td>';
        h += '<td>' + (s.status !== 'active' ? '<button onclick="window._DS.enableStrat(\'' + E(name) + '\')" class="strat-btn strat-btn-primary" style="font-size:12px;padding:2px 8px">启用</button>' : '') + '</td></tr>';
      });
      h += '</tbody></table>';
      h += '<button onclick="window._DS.runBT()" class="strat-btn strat-btn-primary" style="margin-top:8px">手动回测</button>';
    }

    var symbols = Object.keys(results);
    if (!symbols.length) return h + '<div class="tab-empty">暂无回测结果</div>';

    h += '<h3 style="margin-top:16px">回测结果 (' + (summary.count || symbols.length) + ')</h3><table class="status-table"><thead><tr><th>股票</th><th>策略</th><th>夏普</th><th>胜率</th><th>总收益</th><th>最大回撤</th><th>交易数</th></tr></thead><tbody>';
    symbols.forEach(function(sym) {
      Object.keys(results[sym]).forEach(function(strat) {
        var r = results[sym][strat];
        var retCls = r.total_return_pct >= 0 ? 'trend-up' : 'trend-down';
        h += '<tr style="cursor:pointer" onclick="window._DS.btDetail(\'' + E(sym) + '\')">';
        h += '<td>' + E(sym) + '</td><td>' + E(r.strategy_label || strat) + '</td>';
        h += '<td>' + (r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '\u2014') + '</td>';
        h += '<td>' + (r.win_rate_pct != null ? r.win_rate_pct.toFixed(1) + '%' : '\u2014') + '</td>';
        h += '<td class="' + retCls + '">' + r.total_return_pct.toFixed(2) + '%</td>';
        h += '<td>' + (r.max_drawdown_pct != null ? r.max_drawdown_pct.toFixed(2) + '%' : '\u2014') + '</td>';
        h += '<td>' + (r.total_trades || 0) + '</td></tr>';
      });
    });
    h += '</tbody></table>';
    return h;
  }

  function showBacktestDetail(symbol) {
    var modal = document.getElementById('decision-modal');
    var body = document.getElementById('decision-modal-body');
    if (!modal || !body) return;
    modal.style.display = 'flex';
    body.innerHTML = '<div class="spinner">加载中...</div>';
    S.fetchAuth('/backtest/rolling/' + symbol).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { body.innerHTML = '<div class="error-banner">' + E(d.error) + '</div>'; return; }
      var h = '<h3>' + E(symbol) + ' 滚动回测 (' + E(d.label || d.strategy) + ')</h3>';
      h += '<p>训练: ' + d.train_bars + ' 条 | 测试: ' + (d.test_bars || 0) + ' 条 | 窗口: ' + (d.total_windows || 0) + '</p>';
      h += '<p>平均胜率: ' + (d.avg_win_rate || 0) + '% | 平均夏普: ' + (d.avg_sharpe || 0) + ' | 平均收益: ' + (d.avg_return || 0) + '%</p>';
      h += '<p>一致性: ' + ((d.consistency || 0) * 100).toFixed(0) + '% | 最佳参数: ' + JSON.stringify(d.best_params || {}) + '</p>';
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
