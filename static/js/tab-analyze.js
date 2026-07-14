/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Analyze (诊股 / 选股 / 全市场扫描 / 智能扫描)
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;
  var _loading = false, _abort = null;

  function analyzeStock() {
    var input = document.getElementById('stock-input'), sym = (input.value || '').trim();
    if (!sym) { S.showToast('请输入股票代码', 'error'); return; }
    if (_loading) { S.showToast('诊股进行中，请稍候', 'error'); return; }
    _loading = true;
    var name = S.state._stockNames[sym] || '';
    S._showAnalyzeOverlay(sym, name);
    var resultArea = document.getElementById('analyze-result'), chartArea = document.getElementById('chart-container'), positionArea = document.getElementById('position-suggestion');
    if (resultArea) resultArea.style.display = 'none';
    if (chartArea) chartArea.classList.add('chart-container--hidden');
    if (positionArea) positionArea.innerHTML = '';

    S.fetchAuth('/analyze/' + sym, { method: 'POST', timeout: 120000 }).then(function(r) { return r.json(); }).then(function(d) {
      _loading = false; S._hideAnalyzeOverlay();
      if (d.error) { S.showToast(d.error, 'error'); return; }
      renderAnalyze(d);
    }).catch(function(e) { _loading = false; S._hideAnalyzeOverlay(); S.showToast('诊股失败: ' + (e.name === 'TimeoutError' ? '超时' : e.message || '网络错误'), 'error'); });
  }

  function renderAnalyze(d) {
    var resultArea = document.getElementById('analyze-result'), chartArea = document.getElementById('chart-container'), positionArea = document.getElementById('position-suggestion');
    var nameHeader = (d.name ? E(d.name) + ' ' : '') + E(d.symbol);
    var price = d.price != null ? d.price.toFixed(2) : '\u2014';
    var chg = d.change_pct != null ? d.change_pct.toFixed(2) + '%' : '\u2014';
    var chgCls = d.change_pct >= 0 ? 'trend-up' : 'trend-down';

    var h = '<div class="analyze-header" style="margin-bottom:16px">';
    h += '<h2 style="margin:0 0 4px">' + nameHeader + '</h2>';
    h += '<span style="font-size:24px;font-weight:700">' + price + '</span> ';
    h += '<span class="' + chgCls + '" style="font-size:16px;margin-left:8px">' + chg + '</span>';
    if (d.trend) h += ' <span class="badge badge-' + (d.trend === 'bullish' ? 'ok' : d.trend === 'bearish' ? 'warn' : '') + '">' + ({ bullish: '看多', bearish: '看空', sideways: '震荡' }[d.trend] || d.trend) + '</span>';
    h += '</div>';

    if (d.indicators) {
      var ind = d.indicators;
      h += '<div class="tab-section"><h3>技术指标</h3><table class="status-table"><tbody>';
      var rows = [
        ['RSI(14)', ind.rsi != null ? ind.rsi.toFixed(1) : '\u2014'],
        ['MACD DIF/DEA', (ind.macd && ind.macd.dif != null) ? ind.macd.dif.toFixed(3) + ' / ' + ind.macd.dea.toFixed(3) : '\u2014'],
        ['MACD 柱', (ind.macd && ind.macd.histogram != null) ? ind.macd.histogram.toFixed(4) : '\u2014'],
        ['MA5/MA10/MA20', (ind.ma5 || '\u2014') + ' / ' + (ind.ma10 || '\u2014') + ' / ' + (ind.ma20 || '\u2014')],
        ['MA60', ind.ma60 || '\u2014'],
        ['布林带', ind.bollinger ? '上' + ind.bollinger.upper + ' 中' + ind.bollinger.middle + ' 下' + ind.bollinger.lower : '\u2014'],
        ['ATR', ind.atr || '\u2014'],
        ['KDJ', ind.kdj ? 'K' + ind.kdj.k + ' D' + ind.kdj.d + ' J' + ind.kdj.j : '\u2014'],
        ['量比', ind.vol_ratio || '\u2014'],
        ['5日/20日均量', (ind.avg_vol_5 ? Math.round(ind.avg_vol_5 / 10000) + '万' : '\u2014') + ' / ' + (ind.avg_vol_20 ? Math.round(ind.avg_vol_20 / 10000) + '万' : '\u2014')],
      ];
      rows.forEach(function(r) { h += '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>'; });
      h += '</tbody></table></div>';
    }

    if (d.strategy_hits && d.strategy_hits.length) {
      h += '<div class="tab-section"><h3>策略命中 (' + d.strategy_hits.length + ')</h3>';
      d.strategy_hits.forEach(function(s) { h += '<span class="badge badge-ok" style="margin:2px">' + E(s.label) + '</span> '; });
      h += '</div>';
    }

    if (d.decision) {
      var dec = d.decision;
      h += '<div class="tab-section"><h3>AI 决策</h3>';
      h += '<div style="font-size:18px;margin:8px 0"><span class="decision-action action-' + E(dec.action) + '">' + S.fmtAction(dec.action) + '</span> 置信度 ' + ((dec.confidence || 0) * 100).toFixed(0) + '%</div>';
      h += '<div style="font-size:14px;color:var(--text-secondary)">' + E(dec.reasoning || '') + '</div>';
      h += '<div style="font-size:12px;color:var(--text-muted);margin-top:4px">Provider: ' + E(dec.provider || '\u2014') + '</div></div>';
    }

    resultArea.innerHTML = h;
    resultArea.style.display = 'block';
    if (chartArea) {
      chartArea.classList.remove('chart-container--hidden');
      if (typeof Charts !== 'undefined' && Charts.renderKline) Charts.renderKline('chart-container', d.symbol);
    }

    S.fetchAuth('/risk/position/' + d.symbol + '?price=' + (d.price || 10) + '&capital=100000&win_prob=0.5&avg_win=0.03&avg_loss=0.02').then(function(r) { return r.json(); }).then(function(pd) {
      if (positionArea && !pd.error) {
        var lvlLabels = { normal: '正常', elevated: '关注', critical: '危险' };
        positionArea.innerHTML = '<div class="tab-section"><h3>仓位建议</h3>' +
          '<p>风险等级: <b>' + (lvlLabels[pd.risk_level] || pd.risk_level) + '</b> | 乘数: ' + ((pd.risk_multiplier || 1) * 100).toFixed(0) + '%</p>' +
          '<p>建议仓位: <b>' + ((pd.position_pct || 0) * 100).toFixed(1) + '%</b> | 股数: <b>' + (pd.shares || 0) + '</b> | 金额: ' + (pd.amount || 0).toFixed(2) + '</p>' +
          (pd.warning ? '<p style="color:var(--color-yellow)">' + pd.warning + '</p>' : '') + '</div>';
      }
    }).catch(function() {});
  }

  function screenStocks(strategy) {
    var panel = document.getElementById('tab-panel');
    panel.innerHTML = '<div class="spinner">选股中...</div>';
    S.fetchAuth('/screen/' + strategy, { method: 'POST' }).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { panel.innerHTML = '<div class="tab-empty">' + E(d.error) + '</div>'; return; }
      var h = '<h3>' + E(d.strategy || strategy) + ' (' + d.matched + ' 只)</h3>';
      if (d.results && d.results.length) {
        h += '<table class="status-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>量比</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + (r.vol_ratio || 0).toFixed(2) + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
        h += '</tbody></table>';
      } else { h += '<div class="tab-empty">无匹配结果</div>'; }
      panel.innerHTML = h;
    }).catch(function(e) { panel.innerHTML = '<div class="error-banner">选股失败: ' + E(e.message) + '</div>'; });
  }

  function fullScan(strategy) {
    var panel = document.getElementById('tab-panel');
    panel.innerHTML = '<div class="spinner">全市场扫描中...</div>';
    S.fetchAuth('/scan/' + strategy, { method: 'POST', timeout: 60000 }).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { panel.innerHTML = '<div class="tab-empty">' + E(d.error) + '</div>'; return; }
      var h = '<h3>全市场扫描: ' + E(d.strategy || strategy) + ' (' + d.matched + ' 只 / ' + d.total_stocks + ' 只)</h3>';
      h += '<p style="font-size:12px;color:var(--text-muted)">粗筛: ' + (d.rough_filtered || 0) + ' | 深度检查: ' + (d.deep_checked || 0) + ' | 耗时: ' + (d.elapsed_seconds || 0) + 's</p>';
      if (d.results && d.results.length) {
        h += '<table class="status-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>量比</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + (r.vol_ratio || 0).toFixed(2) + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
        h += '</tbody></table>';
      } else { h += '<div class="tab-empty">无匹配结果</div>'; }
      panel.innerHTML = h;
    }).catch(function(e) { panel.innerHTML = '<div class="error-banner">扫描失败: ' + E(e.message) + '</div>'; });
  }

  function smartScan() {
    var panel = document.getElementById('tab-panel');
    panel.innerHTML = '<div class="spinner">智能扫描中...</div>';
    S.fetchAuth('/scan/smart', { method: 'POST', timeout: 120000 }).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { panel.innerHTML = '<div class="tab-empty">' + E(d.error) + '</div>'; return; }
      var h = '<h3>智能扫描 (' + d.scored + ' 只 / ' + d.total + ' 只)</h3>';
      h += '<p style="font-size:12px;color:var(--text-muted)">已检查: ' + (d.checked || 0) + ' | 跳过: ' + (d.skipped || 0) + ' | 耗时: ' + (d.elapsed_seconds || 0) + 's</p>';
      if (d.results && d.results.length) {
        h += '<table class="status-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>策略</th><th>评分</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + E(r.strategy_label || r.strategy) + '</td><td>' + (r.score || 0).toFixed(2) + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
        h += '</tbody></table>';
      } else { h += '<div class="tab-empty">无命中</div>'; }
      panel.innerHTML = h;
    }).catch(function(e) { panel.innerHTML = '<div class="error-banner">扫描失败: ' + E(e.message) + '</div>'; });
  }

  window.TAB_ANALYZE = { analyzeStock: analyzeStock, renderAnalyze: renderAnalyze, screenStocks: screenStocks, fullScan: fullScan, smartScan: smartScan };
})();
