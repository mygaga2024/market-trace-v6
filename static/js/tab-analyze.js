/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Analyze (诊股 / 选股 / 全市场扫描 / 智能扫描)
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;
  var _loading = false;

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
    var trendCn = { bullish: '看多', bearish: '看空', sideways: '震荡' };
    var trendCls = d.trend === 'bullish' ? 'badge-ok' : (d.trend === 'bearish' ? 'badge-warn' : '');

    var h = '<div class="tab-section">';
    h += '<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px">';
    h += '<h2 style="margin:0">' + nameHeader + '</h2>';
    h += '<span style="font-size:26px;font-weight:700">' + price + '</span>';
    h += '<span class="' + chgCls + '" style="font-size:18px;font-weight:600">' + chg + '</span>';
    if (d.trend) h += '<span class="badge ' + trendCls + '" style="font-size:14px;padding:4px 10px">趋势: ' + (trendCn[d.trend] || d.trend) + '</span>';
    if (d.macro_rai != null) h += '<span style="font-size:13px;color:var(--text-muted)">RAI: ' + d.macro_rai.toFixed(2) + '</span>';
    h += '</div></div>';

    if (d.indicators) {
      var ind = d.indicators, macd = ind.macd || {}, bol = ind.bollinger || {}, kdj = ind.kdj || {}, sr = ind.support_resistance || {};
      h += '<div class="tab-section"><h3 class="tab-section-title">技术指标</h3><table class="status-table"><thead><tr><th>指标</th><th>数值</th><th>指标</th><th>数值</th></tr></thead><tbody>';
      var rows = [
        ['MA5', ind.ma5 ? ind.ma5.toFixed(2) : '\u2014', 'MA10', ind.ma10 ? ind.ma10.toFixed(2) : '\u2014'],
        ['MA20', ind.ma20 ? ind.ma20.toFixed(2) : '\u2014', 'MA60', ind.ma60 ? ind.ma60.toFixed(2) : '\u2014'],
        ['RSI(14)', ind.rsi != null ? ind.rsi.toFixed(1) : '\u2014', 'KDJ', kdj.k ? 'K' + kdj.k + ' D' + kdj.d + ' J' + kdj.j : '\u2014'],
        ['MACD DIF', macd.dif != null ? macd.dif.toFixed(3) : '\u2014', 'MACD DEA', macd.dea != null ? macd.dea.toFixed(3) : '\u2014'],
        ['MACD 柱', macd.histogram != null ? macd.histogram.toFixed(4) : '\u2014', 'ATR', ind.atr ? ind.atr.toFixed(2) : '\u2014'],
        ['布林上轨', bol.upper || '\u2014', '布林中轨', bol.middle || '\u2014'],
        ['布林下轨', bol.lower || '\u2014', '布林带宽', bol.bandwidth != null ? bol.bandwidth.toFixed(4) : '\u2014'],
        ['阻力位', sr.resistance || '\u2014', '支撑位', sr.support || '\u2014'],
        ['量比', ind.vol_ratio ? ind.vol_ratio.toFixed(2) : '\u2014', '均量(5日)', ind.avg_vol_5 ? (ind.avg_vol_5 / 1e4).toFixed(1) + '万手' : '\u2014'],
      ];
      rows.forEach(function(r) { h += '<tr><td>' + r[0] + '</td><td style="font-variant-numeric:tabular-nums">' + r[1] + '</td><td>' + r[2] + '</td><td style="font-variant-numeric:tabular-nums">' + r[3] + '</td></tr>'; });
      h += '</tbody></table></div>';
    }

    if (d.trace_signals && d.trace_signals.length) {
      h += '<div class="tab-section"><h3 class="tab-section-title">量价信号 (' + d.trace_signals.length + ')</h3><table class="status-table"><thead><tr><th>类型</th><th>方向</th><th>强度</th></tr></thead><tbody>';
      d.trace_signals.forEach(function(s) { h += '<tr><td>' + E(s.type || '') + '</td><td>' + E(s.direction || '') + '</td><td>' + (s.strength || 0).toFixed(2) + '</td></tr>'; });
      h += '</tbody></table></div>';
    }

    if (d.strategy_hits && d.strategy_hits.length) {
      h += '<div class="tab-section"><h3 class="tab-section-title">策略命中</h3>';
      h += '<div style="display:flex;gap:6px;flex-wrap:wrap">';
      d.strategy_hits.forEach(function(s) { h += '<span class="badge badge-ok" style="font-size:13px;padding:4px 10px">' + E(s.label) + '</span>'; });
      h += '</div></div>';
    }

    if (d.decision) {
      var dec = d.decision;
      h += '<div class="tab-section"><h3 class="tab-section-title">AI 决策</h3>';
      h += '<table class="status-table"><tbody>';
      h += '<tr><td style="width:80px">决策</td><td><span class="decision-action action-' + E(dec.action) + '" style="font-size:16px;padding:4px 12px">' + S.fmtAction(dec.action) + '</span></td></tr>';
      h += '<tr><td>置信度</td><td style="font-weight:700;font-size:16px">' + ((dec.confidence || 0) * 100).toFixed(0) + '%</td></tr>';
      h += '<tr><td>AI 模型</td><td>' + E(dec.provider || '\u2014') + '</td></tr>';
      h += '<tr><td>分析理由</td><td style="line-height:1.6;color:var(--text-secondary)">' + E(dec.reasoning || '\u2014') + '</td></tr>';
      h += '</tbody></table></div>';
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
        var lvlCls = pd.risk_level === 'critical' ? 'color:var(--color-fall)' : (pd.risk_level === 'elevated' ? 'color:var(--color-yellow)' : '');
        positionArea.innerHTML = '<div class="tab-section"><h3 class="tab-section-title">仓位建议</h3><table class="status-table"><tbody>' +
          '<tr><td style="width:80px">风险等级</td><td style="' + (lvlCls || '') + ';font-weight:600">' + (lvlLabels[pd.risk_level] || pd.risk_level) + '</td></tr>' +
          '<tr><td>仓位比例</td><td style="font-weight:700;font-size:16px">' + ((pd.position_pct || 0) * 100).toFixed(1) + '%</td></tr>' +
          '<tr><td>建议股数</td><td>' + (pd.shares || 0) + ' 股</td></tr>' +
          '<tr><td>建议金额</td><td>' + (pd.amount || 0).toFixed(2) + ' 元</td></tr>' +
          '<tr><td>计算方式</td><td style="color:var(--text-secondary)">' + E(pd.detail || pd.method || '') + '</td></tr>' +
          (pd.warning ? '<tr><td>警示</td><td style="color:var(--color-yellow)">' + E(pd.warning) + '</td></tr>' : '') +
          '</tbody></table></div>';
      }
    }).catch(function() {});
  }

  function screenStocks(strategy) {
    var panel = document.getElementById('tab-panel');
    panel.innerHTML = '<div class="spinner">选股中...</div>';
    S.fetchAuth('/screen/' + strategy, { method: 'POST' }).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { panel.innerHTML = '<div class="tab-empty">' + E(d.error) + '</div>'; return; }
      var h = '<h3>' + E(d.strategy || strategy) + ' <span style="font-weight:400;color:var(--text-muted);font-size:14px">匹配 ' + d.matched + ' 只</span></h3>';
      if (d.results && d.results.length) {
        h += '<table class="status-table" style="font-size:13px"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>量比</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + (r.vol_ratio != null ? r.vol_ratio.toFixed(2) : '—') + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
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
      var h = '<h3>全市场: ' + E(d.strategy || strategy) + ' <span style="font-weight:400;color:var(--text-muted);font-size:14px">' + d.matched + '/' + d.total_stocks + ' 只 | 耗时 ' + (d.elapsed_seconds || 0) + 's</span></h3>';
      if (d.results && d.results.length) {
        h += '<table class="status-table" style="font-size:13px"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>量比</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + (r.vol_ratio != null ? r.vol_ratio.toFixed(2) : '—') + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
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
      var h = '<h3>智能扫描 <span style="font-weight:400;color:var(--text-muted);font-size:14px">' + d.scored + '/' + d.total + ' 只 | 耗时 ' + (d.elapsed_seconds || 0) + 's</span></h3>';
      if (d.results && d.results.length) {
        h += '<table class="status-table" style="font-size:13px"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>策略</th><th>评分</th><th></th></tr></thead><tbody>';
        d.results.forEach(function(r) { h += '<tr><td>' + E(r.symbol) + '</td><td>' + E(r.name || '') + '</td><td>' + (r.price || 0).toFixed(2) + '</td><td class="' + (r.change_pct >= 0 ? 'trend-up' : 'trend-down') + '">' + (r.change_pct || 0).toFixed(2) + '%</td><td>' + E(r.strategy_label || r.strategy) + '</td><td>' + (r.score || 0).toFixed(2) + '</td><td>' + S._renderDiagBtn(r.symbol) + '</td></tr>'; });
        h += '</tbody></table>';
      } else { h += '<div class="tab-empty">无命中</div>'; }
      panel.innerHTML = h;
    }).catch(function(e) { panel.innerHTML = '<div class="error-banner">扫描失败: ' + E(e.message) + '</div>'; });
  }

  window.TAB_ANALYZE = { analyzeStock: analyzeStock, renderAnalyze: renderAnalyze, screenStocks: screenStocks, fullScan: fullScan, smartScan: smartScan };
})();
