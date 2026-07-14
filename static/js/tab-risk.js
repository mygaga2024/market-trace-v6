/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Risk History
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6, E = S.escapeHtml;

  function renderRiskHistory(d) {
    var items = d && d.overrides ? d.overrides : [];
    if (!items.length) return '<div class="tab-empty">暂无风控否决事件</div>';
    var h = '<h3>风控否决历史 (' + (d.count || items.length) + ')</h3><table class="status-table"><thead><tr><th>时间</th><th>级别</th><th>措施</th><th>股票</th><th>详情</th></tr></thead><tbody>';
    items.forEach(function(r) {
      var sevCls = r.severity === 'critical' ? 'color:var(--color-fall);font-weight:600' : (r.severity === 'warning' ? 'color:var(--color-yellow)' : '');
      h += '<tr><td>' + S._ts(r.timestamp) + '</td><td style="' + sevCls + '">' + E(r.severity || '') + '</td>';
      h += '<td>' + E(S.RISK_ACTION_LABELS[r.action] || r.action) + '</td>';
      h += '<td>' + E(r.symbol || '\u2014') + '</td><td style="font-size:12px">' + E(r.reason || '') + '</td></tr>';
    });
    h += '</tbody></table>';
    return h;
  }

  window.TAB_RISK = { renderRiskHistory: renderRiskHistory };
})();
