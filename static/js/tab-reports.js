/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Reports (Health, Status, Reports, Decisions, Logs, Paper, Help)
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;

  function renderHealth(d) {
    var h = '<div class="tab-section"><h3 class="tab-section-title">Redis / 数据库</h3>';
    h += '<table class="status-table"><tr><td>Redis</td><td><span class="badge ' + (d.redis === 'connected' ? 'badge-ok' : 'badge-err') + '">' + (d.redis || 'disconnected') + '</span></td></tr>';
    h += '<tr><td>数据库</td><td><span class="badge ' + (d.database === 'connected' ? 'badge-ok' : 'badge-err') + '">' + (d.database || 'disconnected') + '</span></td></tr>';
    h += '<tr><td>运行Agent</td><td>' + (d.agents_running || '\u2014') + '</td></tr>';
    h += '<tr><td>在线时长</td><td>' + S.fmtTime(d.uptime_seconds || 0) + '</td></tr></table></div>';
    if (d.agents) {
      h += '<div class="tab-section"><h3 class="tab-section-title">Agent 心跳</h3><table class="status-table">';
      var names = { macro: '宏观', signal: '信号', trace: '资金', risk: '风控', chief: '首席' };
      Object.keys(names).forEach(function(k) { h += '<tr><td>' + names[k] + '</td><td><span class="dot ' + (d.agents[k] ? 'dot-on' : 'dot-off') + '"></span> ' + (d.agents[k] ? '在线' : '离线') + '</td></tr>'; });
      h += '</table></div>';
    }
    if (d.llm_chain) {
      h += '<div class="tab-section"><h3 class="tab-section-title">LLM 链路</h3><table class="status-table">';
      S.LLM_TIERS.forEach(function(t) { var p = d.llm_chain[t]; if (!p) return; h += '<tr><td>' + E(t) + '</td><td>' + E(p.provider) + '</td><td>' + E(p.model) + '</td><td>' + (p.api_key_configured ? '\u2713' : '\u2717') + '</td></tr>'; });
      h += '</table></div>';
    }
    return h;
  }

  function renderStatus(d) {
    var h = '<div class="tab-section"><h3>系统状态</h3><p>版本: ' + E(d.version || '') + ' | 运行: ' + S.fmtTime(d.uptime_seconds || 0) + '</p></div>';
    if (d.decision_stats) {
      h += '<div class="tab-section"><h3>决策统计</h3><table class="status-table"><tr><td>总数</td><td>' + d.decision_stats.total + '</td></tr>';
      h += '<tr><td>平均置信度</td><td>' + ((d.decision_stats.avg_confidence || 0) * 100).toFixed(0) + '%</td></tr>';
      if (d.decision_stats.action_distribution) {
        ['BUY', 'SELL', 'HOLD', 'WAIT'].forEach(function(a) { h += '<tr><td>' + S.fmtAction(a) + '</td><td>' + (d.decision_stats.action_distribution[a] || 0) + '</td></tr>'; });
      }
      h += '</table></div>';
    }
    if (d.latest_decision) {
      var dec = d.latest_decision;
      h += '<div class="tab-section"><h3>最新决策</h3><span class="decision-action action-' + E(dec.action) + '">' + S.fmtAction(dec.action) + '</span> ' + ((dec.confidence || 0) * 100).toFixed(0) + '%<br>' + E(dec.reasoning || '') + '<br><small>' + S._ts(dec.timestamp) + '</small></div>';
    }
    return h;
  }

  function renderReportList(d, name) {
    var items = d && d.items ? d.items : (Array.isArray(d) ? d : []);
    if (!items.length) return '<div class="tab-empty">暂无' + (name || '报告') + '</div>';
    var h = '<div class="tab-section"><h3 class="tab-section-title">' + E(name) + ' (' + items.length + ')</h3>';
    h += '<table class="status-table" style="font-size:13px"><thead><tr><th>时间</th><th>标的</th><th>摘要</th></tr></thead><tbody>';
    items.forEach(function(r) { h += '<tr><td style="white-space:nowrap;font-size:12px">' + S._ts(r.timestamp) + '</td><td>' + E(r.symbol || '—') + '</td><td style="color:var(--text-secondary)">' + E(r.summary || '') + '</td></tr>'; });
    h += '</tbody></table></div>';
    return h;
  }

  function renderDecisions(d) {
    var items = d && d.items ? d.items : [];
    if (!items.length) return '<div class="tab-empty">暂无决策</div>';
    var h = '<div class="tab-section"><h3 class="tab-section-title">决策历史 (' + items.length + ')</h3>';
    h += '<table class="status-table" style="font-size:13px"><thead><tr><th>时间</th><th>决策</th><th>置信度</th><th>理由</th><th>模型</th></tr></thead><tbody>';
    items.forEach(function(dec) {
      h += '<tr style="cursor:pointer" onclick="window._DS.showDM(\'' + E(dec.decision_id) + '\')">';
      h += '<td style="white-space:nowrap;font-size:12px">' + S._ts(dec.timestamp) + '</td>';
      h += '<td><span class="decision-action action-' + E(dec.action) + '" style="font-size:12px;padding:2px 8px">' + S.fmtAction(dec.action) + '</span></td>';
      h += '<td style="font-weight:600;font-variant-numeric:tabular-nums">' + ((dec.confidence || 0) * 100).toFixed(0) + '%</td>';
      h += '<td style="color:var(--text-secondary);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + E(dec.reasoning || '') + '</td>';
      h += '<td style="font-size:12px;color:var(--text-muted)">' + E(dec.provider_label || '') + '</td></tr>';
    });
    h += '</tbody></table></div>';
    return h;
  }

  function renderLogs(d) {
    var lines = d && d.lines ? d.lines : [];
    if (!lines.length) return '<div class="tab-empty">暂无日志</div>';
    return '<h3>系统日志 (' + (d.count || lines.length) + ')</h3><pre style="background:#0d1117;color:#8b949e;padding:12px;border-radius:8px;font-size:12px;max-height:500px;overflow:auto">' + lines.map(function(l) { return E(l); }).join('\n') + '</pre>';
  }

  function renderPaper(d) {
    if (d.error) return '<div class="tab-empty">' + E(d.error) + '</div>';
    var pnl = d.total_pnl || 0, pnlCls = pnl >= 0 ? 'trend-up' : 'trend-down';
    var h = '<div class="tab-section"><h3 class="tab-section-title">纸上交易</h3>';
    h += '<table class="status-table"><tbody>';
    h += '<tr><td style="width:80px">账户</td><td>' + E(d.account_id || 'default') + '</td></tr>';
    h += '<tr><td>初始本金</td><td>' + (d.initial_capital || 0).toLocaleString() + ' 元</td></tr>';
    h += '<tr><td>可用现金</td><td>' + (d.capital || 0).toLocaleString() + ' 元</td></tr>';
    h += '<tr><td>总权益</td><td>' + (d.total_equity || 0).toLocaleString() + ' 元</td></tr>';
    h += '<tr><td>累计盈亏</td><td class="' + pnlCls + '" style="font-weight:600;font-size:16px">' + (pnl >= 0 ? '+' : '') + pnl.toLocaleString() + ' (' + (d.total_pnl_pct || 0).toFixed(2) + '%)</td></tr>';
    h += '<tr><td>持仓数</td><td>' + (d.position_count || 0) + '</td></tr>';
    h += '<tr><td>总交易</td><td>' + (d.total_trades || 0) + ' 笔</td></tr>';
    h += '<tr><td>总订单</td><td>' + (d.total_orders || 0) + ' 笔</td></tr>';
    h += '</tbody></table></div>';
    if (d.positions && d.positions.length) {
      h += '<div class="tab-section"><h3 class="tab-section-title">持仓明细</h3><table class="status-table" style="font-size:13px"><thead><tr><th>代码</th><th>数量</th><th>均价</th><th>成本</th></tr></thead><tbody>';
      d.positions.forEach(function(p) { h += '<tr><td>' + E(p.symbol) + '</td><td>' + p.quantity + '</td><td>' + p.avg_cost.toFixed(2) + '</td><td>' + p.cost_basis.toLocaleString() + '</td></tr>'; });
      h += '</tbody></table></div>';
    }
    return h;
  }

  function renderHelp() {
    return '<div class="tab-section"><h3>使用指南</h3><div style="font-size:14px;line-height:1.8">' +
      '<p><b>Market Trace V6</b> — A 股量化分析系统，多 Agent + AI 决策。</p>' +
      '<h4>功能</h4><ul>' +
      '<li><b>诊股</b>: 输入代码获取完整分析 + AI 建议</li>' +
      '<li><b>选股</b>: 按策略筛选股票池</li>' +
      '<li><b>全市场扫描</b>: 策略筛选全部 A 股</li>' +
      '<li><b>智能扫描</b>: 7 策略综合评分</li>' +
      '<li><b>回测</b>: 历史回测夏普/胜率/最大回撤</li>' +
      '<li><b>持仓</b>: 关注股票实时价格</li>' +
      '<li><b>纸上交易</b>: 虚拟账户模拟</li></ul>' +
      '<h4>架构</h4><ul>' +
      '<li>5 Agent: 宏观(RAI) / 技术 / 资金 / 风控 / 首席决策</li>' +
      '<li>7 级 LLM: DeepSeek → Gemini → GLM → 千帆 → 纯规则</li>' +
      '<li>数据: AkShare + Tushare，Redis 缓存 + 降级</li></ul>' +
      '<p style="color:var(--text-muted);font-size:12px">版本 1.2.0</p></div></div>';
  }

  window.TAB_REPORTS = { renderHealth: renderHealth, renderStatus: renderStatus, renderReportList: renderReportList, renderDecisions: renderDecisions, renderLogs: renderLogs, renderPaper: renderPaper, renderHelp: renderHelp };
})();
