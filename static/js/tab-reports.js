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
    return '<div class="help-guide">' +
      '<h2>Market Trace V6.0 使用指南</h2>' +
      '<div class="tab-section"><h3 class="tab-section-title">系统概览</h3>' +
      '<p>Market Trace V6.0 是一个 <b>A/B 股量化分析系统</b>，通过 5 个 Agent（宏观/信号/资金/风控/决策）协作 + 7 级 LLM 回退链，对全市场 5000+ A 股进行技术分析、策略扫描和 AI 决策。</p>' +
      '<p>左侧仪表盘卡片实时展示系统健康状态，下方 Tab 面板提供详细数据查阅，底部提供选股策略和全市场扫描功能。</p></div>' +

      '<div class="tab-section"><h3 class="tab-section-title">仪表盘卡片</h3>' +
      '<h4>风险偏好指数 RAI</h4>' +
      '<p>显示当前市场的 Risk Appetite Index（0~1），反映市场投机情绪。点击卡片跳转到宏观报告 Tab。</p>' +
      '<table class="status-table"><tr><td style="color:var(--color-rise)">RAI >= 0.55</td><td>市场乐观，风险偏好高</td></tr>' +
      '<tr><td style="color:var(--color-yellow)">0.45 <= RAI < 0.55</td><td>震荡，方向不明</td></tr>' +
      '<tr><td style="color:var(--color-fall)">RAI < 0.45</td><td>市场悲观，避险情绪浓</td></tr></table>' +
      '<h4 style="margin-top:12px">运行 Agent</h4>' +
      '<p>展示 5 个 Agent 的存活状态。绿点亮起表示该 Agent 正常运行。点击跳转到健康检查 Tab。</p>' +
      '<ul><li><b>宏观 Macro</b> — 采集指数、计算 RAI</li>' +
      '<li><b>信号 Signal</b> — 计算 14 项技术指标</li>' +
      '<li><b>资金 Trace</b> — 监控资金流向、大单异动</li>' +
      '<li><b>风控 Risk</b> — 实时风险监控、否决异常决策</li>' +
      '<li><b>决策 Chief</b> — 综合多源证据，输出 BUY/SELL/HOLD</li></ul>' +
      '<h4 style="margin-top:12px">AI 决策链</h4>' +
      '<p>系统使用七级 LLM 回退链确保决策不中断。绿勾表示该级 API Key 已配置可用。</p>' +
      '<p style="font-size:12px;color:var(--text-secondary)"><code>DeepSeek Chat → DeepSeek Reasoner → Gemini K1 → Gemini K2 → GLM Flash → 硅基流动 → 百度千帆 → 纯规则</code></p>' +
      '<p>任一环节熔断或超时自动降级到下一级，最终由纯规则兜底。</p>' +
      '<h4 style="margin-top:12px">风控闭环</h4>' +
      '<p>Risk Agent 实时监控市场风险和 AI 决策质量。当出现异常时自动否决决策或降权置信度。</p>' +
      '<h4 style="margin-top:12px">持仓列表</h4>' +
      '<p>添加关注的股票，系统显示实时价格和涨跌幅。点击股票名称可快速诊股，拖拽可自行排序，点击 × 可移除。</p></div>' +

      '<div class="tab-section"><h3 class="tab-section-title">Tab 面板说明</h3>' +
      '<table class="status-table"><thead><tr><th>Tab</th><th>功能说明</th></tr></thead><tbody>' +
      '<tr><td>健康检查</td><td>系统运行状态：版本号、运行时间、Redis/数据库连接、LLM 链路、Agent 心跳</td></tr>' +
      '<tr><td>状态详情</td><td>运行统计：决策统计、案例统计、最新决策详情</td></tr>' +
      '<tr><td>宏观报告</td><td>Macro Agent 定期生成的宏观分析，包含 RAI 指数、市场情绪评估</td></tr>' +
      '<tr><td>信号报告</td><td>Signal Agent 技术信号报告：指标计算、策略命中情况</td></tr>' +
      '<tr><td>资金报告</td><td>Trace Agent 资金流向报告：大单异动、量价异常</td></tr>' +
      '<tr><td>决策历史</td><td>最近 AI 决策记录，点击行可查看完整推理链和证据来源。按 Esc 关闭弹窗</td></tr>' +
      '<tr><td>风控历史</td><td>风控否决事件：级别、规则、股票、处理动作</td></tr>' +
      '<tr><td>策略回测</td><td>股票池×7策略回测结果（夏普/胜率/回撤/Alpha/Beta）。点击股票行展开详情</td></tr>' +
      '<tr><td>系统日志</td><td>最近 100 行服务器日志，用于排查异常</td></tr>' +
      '<tr><td>纸上交易</td><td>虚拟账户模拟交易：持仓明细、累计盈亏、交易记录</td></tr>' +
      '</tbody></table></div>' +

      '<div class="tab-section"><h3 class="tab-section-title">底部功能</h3>' +
      '<h4>诊股</h4><p>输入股票代码（如 000001），系统拉取 K 线 → 计算 14 项技术指标 → 检测 7 策略信号 → 调 LLM 做 AI 决策。结果包含完整的指标数值、策略命中、AI 建议和仓位计算。</p>' +
      '<h4>选股策略</h4><p>按策略（强势突破/超跌反弹/主力介入/风险预警）扫描股票池中的标的，返回匹配结果。</p>' +
      '<h4>全市场扫描</h4><p>对 5000+ A 股做全市场策略扫描（粗筛+深度检查），耗时约 5-30 秒。智能综合扫描会对有缓存 K 线的股票做 7 策略评分排序。</p></div>' +
      '<p style="color:var(--text-muted);font-size:12px;text-align:center;margin-top:16px">版本 1.3.5 | Market Trace V6</p></div>';
  }

  window.TAB_REPORTS = { renderHealth: renderHealth, renderStatus: renderStatus, renderReportList: renderReportList, renderDecisions: renderDecisions, renderLogs: renderLogs, renderPaper: renderPaper, renderHelp: renderHelp };
})();
