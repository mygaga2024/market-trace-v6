/* ──────────────────────────────────────
   Market Trace V6.0 — Tab: Watchlist
   ────────────────────────────────────── */
(function() {
  'use strict';
  var S = window.MT6;

  function refreshWatchlist() {
    var cont = document.getElementById('watchlist-items');
    if (cont) cont.innerHTML = '<div style="color:var(--text-muted);font-size:13px">刷新中...</div>';
    S.fetchAuth('/watchlist').then(function(r) { return r.json(); }).then(function(d) {
      var items = (d && d.items) ? S._applyWlSortOrder(d.items) : [];
      items.forEach(function(it) { if (it.name) S.state._stockNames[it.symbol] = it.name; });
      if (cont) cont.innerHTML = S._renderWatchlistItems(items);
    }).catch(function() { if (cont) cont.innerHTML = '<div style="color:var(--text-fall)">刷新失败</div>'; });
  }

  function addToWatchlist() {
    var input = document.getElementById('watchlist-input'), sym = (input.value || '').trim();
    if (!sym) { S.showToast('请输入股票代码', 'error'); return; }
    S.fetchAuth('/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym }) })
      .then(function(r) { return r.json(); }).then(function(d) {
        if (d.error) { S.showToast(d.error, 'error'); return; }
        input.value = ''; S.showToast(sym + ' 已添加', 'success');
        S.load();
      }).catch(function(e) { S.showToast('添加失败: ' + (e.message || ''), 'error'); });
  }

  function removeFromWatchlist(symbol) {
    S.fetchAuth('/watchlist/' + symbol, { method: 'DELETE' }).then(function(r) { return r.json(); }).then(function(d) {
      if (d.error) { S.showToast(d.error, 'error'); return; }
      S.showToast(symbol + ' 已移除', 'success');
      S.load();
    }).catch(function(e) { S.showToast('移除失败: ' + (e.message || ''), 'error'); });
  }

  window.TAB_WATCHLIST = { refreshWatchlist: refreshWatchlist, addToWatchlist: addToWatchlist, removeFromWatchlist: removeFromWatchlist };
})();
