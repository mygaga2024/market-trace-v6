(function () {
  "use strict";

  var VIEWS = {
    stocks: {
      eyebrow: "资产身份",
      title: "股票管理",
      description: "维护自选股票、信号状态、风险偏好和一次性决策记录。"
    },
    trade: {
      eyebrow: "交易执行",
      title: "交易终端",
      description: "查看账户、持仓与委托；模拟盘可直接下单，实盘需官方券商网关。"
    },
    overview: {
      eyebrow: "市场身份",
      title: "控制总览",
      description: "聚合主要指数、自选行情、风险偏好与最近一次量化决策。"
    },
    signals: {
      eyebrow: "实时运营",
      title: "实时决策",
      description: "查看最新量化结论、置信度与当前市场风险状态。"
    },
    audit: {
      eyebrow: "安全运营",
      title: "审计日志",
      description: "追踪每一次自选变更、策略切换、风控配置和分析决策。"
    },
    analyze: {
      eyebrow: "分析工具",
      title: "智能诊股",
      description: "读取实时行情与 140 日 K 线，生成可解释的技术面决策。"
    },
    strategies: {
      eyebrow: "分析工具",
      title: "策略配置",
      description: "选择参与量化评分的技术策略，修改后会记录审计事件。"
    },
    portfolio: {
      eyebrow: "资产管理",
      title: "持仓管理",
      description: "统一查看关注标的、实时价格、量化结论与风险标签。"
    },
    custody: {
      eyebrow: "资产管理",
      title: "托管交易",
      description: "设置量化阈值、检查频率与单次上限，由托管引擎自动提交委托。"
    },
    risk: {
      eyebrow: "组织权限",
      title: "风控配置",
      description: "维护单票仓位、止损、单日亏损和最低决策置信度。"
    },
    history: {
      eyebrow: "资产管理",
      title: "决策历史",
      description: "回看每次诊股生成的动作、评分、风险与决策依据。"
    },
    users: {
      eyebrow: "组织权限",
      title: "用户管理",
      description: "维护本地账户、角色与交易权限；仅管理员可执行此操作。"
    },
    agents: {
      eyebrow: "系统管理",
      title: "Agent 设置",
      description: "检查行情、量化、风控、记忆和接口模块的运行状态。"
    },
    system: {
      eyebrow: "系统管理",
      title: "系统管理",
      description: "查看 Go 服务版本、数据源、持久化路径和运行参数。"
    }
  };

  var state = {
    data: null,
    view: "stocks",
    search: "",
    railSearch: "",
    stockFilter: "all",
    analysis: null,
    tradeSide: "BUY",
    users: [],
    usersLoaded: false,
    loading: false,
    toastTimer: null
  };

  var viewRoot = document.getElementById("view-root");
  var watchList = document.getElementById("watch-list");
  var title = document.getElementById("page-title");
  var eyebrow = document.getElementById("page-eyebrow");
  var description = document.getElementById("page-description");
  var marketPill = document.getElementById("market-pill");
  var dataStrip = document.getElementById("data-strip");
  var dataStripText = document.getElementById("data-strip-text");
  var stockDialog = document.getElementById("stock-dialog");
  var stockForm = document.getElementById("stock-form");
  var stockFormError = document.getElementById("stock-form-error");
  var toast = document.getElementById("toast");

  function api(path, options) {
    var opts = options || {};
    opts.credentials = "same-origin";
    if (opts.body && typeof opts.body !== "string") {
      opts.headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (payload) {
        if (response.status === 401) {
          location.assign("/login");
          throw new Error("登录已失效");
        }
        if (!response.ok) {
          throw new Error(payload.error || "请求失败（HTTP " + response.status + "）");
        }
        return payload;
      });
    });
  }

  function loadDashboard(options) {
    var silent = options && options.silent;
    if (!silent) {
      setLoading(true);
    }
    var refreshButton = document.getElementById("refresh-button");
    if (refreshButton) {
      refreshButton.disabled = true;
    }
    return api("/api/v1/dashboard").then(function (payload) {
      state.data = payload;
      renderCurrentUser();
      renderHeader();
      renderView();
      renderRail();
      if (!silent) {
        setLoading(false);
      }
      if (refreshButton) {
        refreshButton.disabled = false;
      }
    }).catch(function (error) {
      setLoading(false);
      if (refreshButton) {
        refreshButton.disabled = false;
      }
      viewRoot.innerHTML = errorState("无法读取市场数据", error.message);
      showToast(error.message, true);
    });
  }

  function renderCurrentUser() {
    if (!state.data || !state.data.current_user) {
      return;
    }
    var user = state.data.current_user;
    var name = user.display_name || user.username;
    document.getElementById("user-name").textContent = name;
    document.getElementById("user-role").textContent = user.role === "owner" ? "OWNER" : "TRADER";
    document.getElementById("user-avatar").textContent = name.slice(0, 1).toUpperCase();
  }

  function setLoading(loading) {
    state.loading = loading;
    if (loading && !state.data) {
      viewRoot.innerHTML = '<div class="loading-state"><span class="loading-ring"></span><strong>正在读取市场数据</strong><small>连接行情源与本地决策记录…</small></div>';
    }
  }

  function renderHeader() {
    var meta = VIEWS[state.view] || VIEWS.stocks;
    title.textContent = meta.title;
    eyebrow.textContent = meta.eyebrow;
    description.textContent = meta.description;
    document.title = meta.title + " · Market Trace";

    if (!state.data) {
      return;
    }
    var live = state.data.overview.live_market;
    marketPill.classList.toggle("degraded", !live);
    marketPill.querySelector("span").textContent = live ? "实时行情" : "降级行情";

    if (!live) {
      dataStrip.hidden = false;
      dataStripText.textContent = state.data.overview.data_source === "stale-cache"
        ? "实时行情连接异常，当前显示上一轮缓存价格；决策分数仍按最近一次分析保留。"
        : "实时行情暂不可用，价格字段会明确显示为 —，不会用占位值参与评分。";
    } else {
      dataStrip.hidden = true;
    }
  }

  function renderView() {
    if (!state.data) {
      return;
    }
    var renderers = {
      overview: renderOverview,
      stocks: renderStocks,
      trade: renderTrade,
      signals: renderSignals,
      audit: renderAudit,
      analyze: renderAnalyze,
      strategies: renderStrategies,
      portfolio: renderPortfolio,
      custody: renderCustody,
      risk: renderRisk,
      history: renderHistory,
      users: renderUsers,
      agents: renderAgents,
      system: renderSystem
    };
    var renderer = renderers[state.view] || renderStocks;
    viewRoot.innerHTML = renderer();
  }

  function renderOverview() {
    var data = state.data;
    var overview = data.overview;
    var risk = data.risk;
    var analyzed = data.stocks.filter(function (stock) { return stock.score !== null; }).length;
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("自选股票", overview.watch_count, "已纳入实时行情监控", "grid") +
        statCard("今日上涨", overview.positive_count + " / " + overview.watch_count, "下跌 " + overview.negative_count + " 只", "pulse") +
        statCard("风险偏好 RAI", risk.rai === null ? "—" : number(risk.rai, 0), risk.rai === null ? "行情数据不足" : risk.label + " · " + riskLabel(risk.level), "shield", true) +
        statCard("已完成分析", analyzed + " / " + overview.watch_count, analyzed ? "平均评分 " + (overview.average_score === null ? "—" : number(overview.average_score, 1)) : "从智能诊股开始", "chart") +
      '</div>' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>主要指数</h2><p>上证 · 深证 · 创业板 · 科创 50 · 沪深 300</p></div>' +
          '<span class="tag neutral">' + escape(overview.live_market ? "实时" : "缓存 / 不可用") + '</span></div>' +
        renderIndexGrid(data.indices) +
      '</section>' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>最近决策</h2><p>由 Go 量化引擎生成并写入本地审计记录</p></div>' +
          '<button class="small-action" type="button" data-go-view="history">全部记录</button></div>' +
        renderDecisionList(data.decisions.slice(0, 5), true) +
      '</section>' +
    '</div>';
  }

  function renderStocks() {
    var data = state.data;
    var stocks = filteredStocks(data.stocks);
    var analyzed = data.stocks.filter(function (stock) { return stock.score !== null; }).length;
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("监控标的", data.overview.watch_count, "全部自选股票", "grid") +
        statCard("实时上涨", data.overview.positive_count, "按最新涨跌幅统计", "pulse") +
        statCard("已评估", analyzed, "存在量化评分与风险标签", "shield", true) +
        statCard("风险等级", riskLabel(data.overview.risk_level), data.risk.missing_quotes ? data.risk.missing_quotes + " 只行情缺失" : "基于自选宽度与指数动量", "lock") +
      '</div>' +
      '<section class="panel">' +
        '<div class="panel-head">' +
          '<div class="panel-title"><h2>股票名单</h2><p>' + stocks.length + ' 只标的 · 行情更新 ' + timeText(data.generated_at) + '</p></div>' +
          '<div class="panel-tools">' +
            '<div class="segmented" role="group" aria-label="筛选股票">' +
              filterButton("all", "全部") + filterButton("up", "上涨") + filterButton("down", "下跌") + filterButton("analyzed", "已分析") +
            '</div>' +
            '<button class="small-action" type="button" data-open-stock><svg><use href="#i-plus"></use></svg>添加</button>' +
          '</div>' +
        '</div>' +
        renderStockTable(stocks) +
      '</section>' +
    '</div>';
  }

  function renderSignals() {
    var data = state.data;
    var highRisk = data.risk.high_risk_symbols || [];
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("风险偏好", data.risk.rai === null ? "—" : number(data.risk.rai, 0), data.risk.label, "shield", true) +
        statCard("上涨 / 下跌", data.risk.up + " / " + data.risk.down, "平盘 " + data.risk.flat + " 只", "pulse") +
        statCard("高风险标的", highRisk.length, highRisk.length ? highRisk.join(" · ") : "暂无", "lock") +
        statCard("决策总数", data.overview.decision_count, "持久化到本地 JSON 日志", "audit") +
      '</div>' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>决策信号流</h2><p>动作采用国内交易语义，风险来自波动率、RSI 与信号分歧</p></div>' +
          '<span class="live-pill' + (data.overview.live_market ? '' : ' degraded') + '"><i></i><span>' + escape(data.overview.live_market ? "引擎在线" : "行情降级") + '</span></span></div>' +
        renderDecisionList(data.decisions, true) +
      '</section>' +
    '</div>';
  }

  function renderAudit() {
    var audits = state.data.audits;
    return '<section class="panel">' +
      '<div class="panel-head"><div class="panel-title"><h2>操作时间线</h2><p>最近 ' + audits.length + ' 条审计事件 · 新事件自动置顶</p></div>' +
        '<span class="tag neutral">不可变更记录</span></div>' +
      renderAuditList(audits) +
    '</section>';
  }

  function renderAnalyze() {
    var analysis = state.analysis;
    var quick = state.data.stocks.slice(0, 5).map(function (stock) {
      return '<button class="tag neutral" type="button" data-analyze-symbol="' + escape(stock.symbol) + '">' +
        escape(stock.name || stock.symbol) + ' · ' + escape(stock.symbol) + '</button>';
    }).join(" ");
    return '<div class="analyze-layout">' +
      '<section class="panel analyze-form">' +
        '<span class="dialog-kicker">QUANT DIAGNOSIS</span>' +
        '<h2>输入股票代码</h2>' +
        '<p>系统将拉取最近 140 个交易日，计算均线、RSI、MACD、KDJ、ATR 与布林带，并记录本次决策。</p>' +
        '<form id="analyze-form" class="inline-form">' +
          '<input class="input" id="analyze-symbol" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="例如 600519" required>' +
          '<button class="button button-primary" type="submit">开始分析</button>' +
        '</form>' +
        '<div style="margin-top:18px">' + quick + '</div>' +
      '</section>' +
      (analysis ? renderAnalysis(analysis) : renderAnalysisPlaceholder()) +
    '</div>';
  }

  function renderAnalysisPlaceholder() {
    return '<section class="panel analysis-placeholder">' +
      '<div><span class="empty-icon"><svg><use href="#i-chart"></use></svg></span>' +
      '<h2>等待生成量化结论</h2>' +
      '<p>输入股票代码或点击左侧自选标的。所有指标都基于真实 K 线计算，数据不足时会明确标注。</p></div>' +
    '</section>';
  }

  function renderAnalysis(analysis) {
    var signals = analysis.signals || [];
    var signalHtml = signals.length ? signals.map(function (signal) {
      return '<div class="signal-item ' + escape(signal.direction) + '">' +
        '<span class="signal-arrow">' + (signal.direction === "bullish" ? "↑" : "↓") + '</span>' +
        '<div class="signal-copy"><strong>' + escape(signal.label) + '</strong><p>' + escape(signal.evidence) + '</p></div>' +
        '<div class="signal-strength"><span>' + number(signal.strength * 100, 0) + '%</span><i><b style="width:' + Math.max(4, Math.min(100, signal.strength * 100)) + '%"></b></i></div>' +
      '</div>';
    }).join("") : '<div class="empty-state" style="min-height:140px"><div><h3>本轮未触发策略信号</h3><p>指标没有形成足够明确的方向证据，因此保持观察。</p></div></div>';

    var ind = analysis.indicators || {};
    return '<section class="panel analysis-result">' +
      '<div class="analysis-hero">' +
        '<div><span class="dialog-kicker">' + escape(analysis.symbol) + ' · ' + escape(analysis.data_source) + '</span>' +
          '<h2>' + escape(analysis.name) + '</h2><p>' + timeText(analysis.generated_at) + ' · ' + (analysis.data_complete ? "完整样本" : "样本不足 60 日") + '</p></div>' +
        '<div class="analysis-price"><strong>' + money(analysis.price) + '</strong><span class="' + changeClass(analysis.change_pct) + '">' + changeText(analysis.change_pct) + '</span></div>' +
      '</div>' +
      '<div class="analysis-verdict">' +
        verdict("综合评分", analysis.score + " / 100") +
        verdict("建议动作", actionLabel(analysis.action)) +
        verdict("风险等级", analysis.risk) +
      '</div>' +
      '<div class="analysis-chart"><div class="chart-head"><strong>近 80 日收盘走势</strong><span>真实 K 线 · 前复权</span></div>' + sparkChart(analysis.bars) + '</div>' +
      '<div class="analysis-summary">' + escape(analysis.summary) + '</div>' +
      '<div class="panel-body" style="padding-bottom:4px"><div class="settings-grid" style="padding:0 0 14px">' +
        kv("MA5 / MA20", indicatorPair(ind.ma5, ind.ma20)) +
        kv("RSI14", indicator(ind.rsi14)) +
        kv("MACD 柱", indicator(ind.macd_histogram, 3)) +
        kv("ATR14", indicator(ind.atr14)) +
        kv("量比", indicator(ind.volume_ratio, 2)) +
        kv("趋势", ind.trend || "—") +
      '</div></div>' +
      '<div class="signal-list">' + signalHtml + '</div>' +
    '</section>';
  }

  function renderStrategies() {
    var cards = state.data.strategies.map(function (strategy) {
      return '<article class="strategy-card">' +
        '<div><h3>' + escape(strategy.name) + '</h3><p>' + escape(strategy.description) + '</p></div>' +
        '<button class="switch ' + (strategy.enabled ? "on" : "") + '" type="button" role="switch" aria-checked="' + strategy.enabled + '" aria-label="' + escape(strategy.name) + '" data-strategy="' + escape(strategy.key) + '" data-enabled="' + strategy.enabled + '"></button>' +
      '</article>';
    }).join("");
    return '<section class="panel">' +
      '<div class="panel-head"><div class="panel-title"><h2>技术策略开关</h2><p>开关状态立即生效，并写入审计日志</p></div>' +
        '<span class="tag neutral">5 类策略</span></div>' +
      '<div class="strategy-grid">' + cards + '</div>' +
    '</section>';
  }

  function renderPortfolio() {
    var stocks = filteredStocks(state.data.stocks);
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("持仓 / 关注", state.data.overview.watch_count, "统一名单", "wallet") +
        statCard("上涨标的", state.data.overview.positive_count, "实时涨跌幅", "pulse") +
        statCard("平均评分", state.data.overview.average_score === null ? "—" : number(state.data.overview.average_score, 1), "仅统计已分析股票", "chart", true) +
        statCard("最大单票上限", number(state.data.settings.max_position_pct, 0) + "%", "来自风控配置", "shield") +
      '</div>' +
      '<section class="panel"><div class="panel-head"><div class="panel-title"><h2>资产名单</h2><p>点击诊股可刷新单只股票的量化结论</p></div>' +
        '<button class="small-action" type="button" data-open-stock><svg><use href="#i-plus"></use></svg>添加标的</button></div>' +
        renderStockTable(stocks) + '</section>' +
    '</div>';
  }

  function renderTrade() {
    var account = state.data.account || {};
    var trading = state.data.trading || {};
    var isLive = trading.mode === "live";
    var orders = state.data.orders || [];
    var side = state.tradeSide === "SELL" ? "SELL" : "BUY";
    return '<div class="view-stack">' +
      '<div class="trading-banner' + (isLive ? " live" : "") + '">' +
        '<svg><use href="#i-' + (isLive ? "bolt" : "shield") + '"></use></svg>' +
        '<div><strong>' + (isLive ? "实盘执行通道" : "模拟交易模式") + '</strong>' +
          escape(trading.message || "交易通道状态未知") + '</div>' +
      '</div>' +
      '<div class="trade-layout">' +
        '<div class="trade-stack">' +
          renderAccountHero(account, trading) +
          '<section class="panel">' +
            '<div class="panel-head"><div class="panel-title"><h2>当前持仓</h2><p>' + (account.positions || []).length + ' 个持仓标的 · 由 ' + escape(account.broker || trading.broker || "—") + ' 返回</p></div>' +
              '<span class="mode-badge ' + (isLive ? "live" : "") + '">' + (isLive ? "LIVE" : "PAPER") + '</span></div>' +
            renderPositions(account.positions || []) +
          '</section>' +
          '<section class="panel">' +
            '<div class="panel-head"><div class="panel-title"><h2>最近委托</h2><p>手动委托与托管委托均在审计日志中留痕</p></div>' +
              '<button class="small-action" type="button" data-open-trade>刷新委托</button></div>' +
            renderOrders(orders.slice(0, 12)) +
          '</section>' +
        '</div>' +
        '<section class="panel order-ticket">' +
          '<span class="dialog-kicker">ORDER TICKET</span>' +
          '<h2>提交委托</h2>' +
          '<p>' + (isLive ? "当前为实盘模式，订单会发送到已配置的官方券商网关。" : "当前为模拟盘，成交只更新本地模拟账户，不会发送到券商。") + '</p>' +
          '<div class="trade-side-tabs">' +
            '<button class="trade-side buy ' + (side === "BUY" ? "active" : "") + '" type="button" data-trade-side="BUY">买入</button>' +
            '<button class="trade-side sell ' + (side === "SELL" ? "active" : "") + '" type="button" data-trade-side="SELL">卖出</button>' +
          '</div>' +
          '<form id="order-form">' +
            '<div class="order-fields">' +
              '<label class="field full"><span>股票代码</span><input class="input" name="symbol" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="例如 600519" required></label>' +
              '<label class="field"><span>数量 <em>股</em></span><input class="input" name="quantity" type="number" min="1" step="1" value="100" required></label>' +
              '<label class="field"><span>委托类型</span><select class="input" name="order_type" id="order-type"><option value="MARKET">市价委托</option><option value="LIMIT">限价委托</option></select></label>' +
              '<label class="field full" id="limit-price-field" hidden><span>限价 <em>元</em></span><input class="input" name="limit_price" type="number" min="0.01" step="0.01" placeholder="输入限价"></label>' +
              '<label class="field full"><span>委托理由 <em>可选</em></span><input class="input" name="reason" maxlength="200" placeholder="例如 突破前高，量价确认"></label>' +
            '</div>' +
            '<button class="button order-submit ' + (side === "BUY" ? "buy" : "sell") + '" type="submit">' + (isLive ? "提交实盘" : "模拟") + (side === "BUY" ? "买入" : "卖出") + '</button>' +
          '</form>' +
        '</section>' +
      '</div>' +
    '</div>';
  }

  function renderAccountHero(account, trading) {
    return '<section class="account-hero">' +
      '<div class="account-hero-top"><div><span class="dialog-kicker">' + escape(trading.mode === "live" ? "LIVE ACCOUNT" : "PAPER ACCOUNT") + '</span>' +
        '<h2>' + money(account.total_equity) + '</h2><p>总资产 · 更新于 ' + timeText(account.updated_at) + '</p></div>' +
        '<span class="mode-badge ' + (trading.mode === "live" ? "live" : "") + '">' + escape(account.broker || trading.broker || "—") + '</span></div>' +
      '<div class="account-metrics">' +
        '<div class="account-metric"><span>可用资金</span><strong>' + money(account.cash) + '</strong></div>' +
        '<div class="account-metric"><span>持仓市值</span><strong>' + money(account.market_value) + '</strong></div>' +
        '<div class="account-metric"><span>当日盈亏</span><strong class="' + (account.day_pnl > 0 ? "up" : account.day_pnl < 0 ? "down" : "") + '">' + signedMoney(account.day_pnl) + '</strong></div>' +
      '</div>' +
    '</section>';
  }

  function renderPositions(positions) {
    if (!positions.length) {
      return '<div class="empty-state" style="min-height:190px"><div><span class="empty-icon"><svg><use href="#i-wallet"></use></svg></span><h3>暂无持仓</h3><p>成交后的持仓会显示在这里。</p></div></div>';
    }
    return '<div class="table-wrap"><table class="stock-table"><thead><tr><th>股票</th><th>持仓 / 可用</th><th>成本价</th><th>现价</th><th>市值</th><th>浮动盈亏</th></tr></thead><tbody>' +
      positions.map(function (position) {
        return '<tr><td><div class="stock-cell">' + stockAvatar(position.name || position.symbol, "stock-avatar") +
          '<div class="stock-main"><strong>' + escape(position.name || position.symbol) + '</strong><span>' + escape(position.symbol) + '</span></div></div></td>' +
          '<td>' + position.quantity + ' / ' + position.available + '</td>' +
          '<td>' + money(position.avg_cost) + '</td>' +
          '<td>' + money(position.last_price) + '</td>' +
          '<td>' + money(position.market_value) + '</td>' +
          '<td class="' + (position.unrealized_pnl > 0 ? "up" : position.unrealized_pnl < 0 ? "down" : "") + '">' + signedMoney(position.unrealized_pnl) + '<br><small>' + signedPercent(position.unrealized_pct) + '</small></td></tr>';
      }).join("") + '</tbody></table></div>';
  }

  function renderOrders(orders) {
    if (!orders.length) {
      return '<div class="empty-state" style="min-height:170px"><div><h3>暂无委托</h3><p>提交一笔模拟委托，或开启托管交易。</p></div></div>';
    }
    return '<div class="table-wrap"><table class="stock-table"><thead><tr><th>时间</th><th>股票</th><th>方向</th><th>数量</th><th>成交价</th><th>状态</th><th>来源</th><th>操作</th></tr></thead><tbody>' +
      orders.map(function (order) {
        var statusClass = String(order.status || "").toLowerCase();
        return '<tr><td>' + timeText(order.created_at, true) + '</td>' +
          '<td><strong>' + escape(order.name || order.symbol) + '</strong><br><small>' + escape(order.symbol) + '</small></td>' +
          '<td><span class="tag ' + (order.side === "BUY" ? "buy" : "sell") + '">' + (order.side === "BUY" ? "买入" : "卖出") + '</span></td>' +
          '<td>' + order.quantity + '</td><td>' + (order.avg_fill_price ? money(order.avg_fill_price) : "—") + '</td>' +
          '<td><span class="order-status ' + statusClass + '">' + orderStatusLabel(order.status) + '</span></td>' +
          '<td>' + (order.source === "custody" ? "托管" : "手动") + '</td>' +
          '<td>' + (order.status === "PENDING" ? '<button class="small-action danger" type="button" data-cancel-order="' + escape(order.id) + '">撤单</button>' : "—") + '</td></tr>';
      }).join("") + '</tbody></table></div>';
  }

  function renderCustody() {
    var settings = state.data.custody || {};
    var status = state.data.trading || {};
    var enabled = Boolean(settings.enabled);
    var live = status.mode === "live";
    return '<div class="view-stack">' +
      '<div class="trading-banner' + (live ? " live" : "") + '">' +
        '<svg><use href="#i-' + (live ? "bolt" : "robot") + '"></use></svg>' +
        '<div><strong>' + (live ? "实盘托管通道" : "模拟托管通道") + '</strong>' +
          escape(live && !status.custody_live_allowed ? "服务端未开启 ALLOW_LIVE_CUSTODY，实盘托管保持锁定。" : status.message) + '</div>' +
      '</div>' +
      '<section class="panel">' +
        '<div class="custody-status">' +
          '<div class="custody-state ' + (enabled ? "on" : "") + '"><span class="custody-pulse"></span><div>' +
            '<strong>' + (enabled ? "托管交易运行中" : "托管交易已停止") + '</strong>' +
            '<span>' + (enabled ? "引擎会按设定间隔检查评分并提交委托。" : "开启前请确认账户、网关和风控参数。") + '</span></div></div>' +
          '<div class="custody-actions">' +
            '<button class="button button-secondary" type="button" data-custody-run>立即检查一次</button>' +
            '<button class="button ' + (enabled ? "button-secondary" : "button-primary") + '" type="button" data-custody-toggle="' + (enabled ? "off" : "on") + '">' + (enabled ? "停止托管" : "开启托管") + '</button>' +
          '</div>' +
        '</div>' +
        '<form id="custody-form" class="custody-form">' +
          '<div class="settings-grid" style="padding:0">' +
            fieldNumber("buy_score", "买入评分阈值", settings.buy_score, "分", "50", "100") +
            fieldNumber("sell_score", "卖出评分阈值", settings.sell_score, "分", "0", "50") +
            fieldNumber("min_confidence", "最低置信度", Math.round((settings.min_confidence || 0) * 100), "%", "50", "95") +
            fieldNumber("max_order_value", "单次委托上限", settings.max_order_value, "元", "100", "10000000") +
            fieldNumber("interval_seconds", "检查间隔", settings.interval_seconds, "秒", "60", "86400") +
            '<label class="field custody-symbols full"><span>托管股票 <em>逗号分隔</em></span><textarea name="symbols" placeholder="600519,300750">' + escape((settings.symbols || []).join(", ")) + '</textarea></label>' +
          '</div>' +
          '<div class="custody-checks"><label><input type="checkbox" name="allow_buy" ' + (settings.allow_buy ? "checked" : "") + '> 允许买入</label>' +
            '<label><input type="checkbox" name="allow_sell" ' + (settings.allow_sell ? "checked" : "") + '> 允许卖出</label></div>' +
          '<div class="settings-summary" style="margin:19px 0 0"><p>托管引擎只使用评分、置信度和风控上限做确定性判断；不保证收益，也不会绕过券商风控。</p>' +
            '<button class="button button-primary" type="submit">保存参数</button></div>' +
        '</form>' +
        '<div class="custody-last">最近检查：' + (settings.last_run_at ? timeText(settings.last_run_at, true) : "尚未运行") + '<br>' +
          escape(settings.last_result || "没有运行结果") + '</div>' +
      '</section>' +
    '</div>';
  }

  function renderUsers() {
    if (!state.usersLoaded) {
      return '<div class="loading-state"><span class="loading-ring"></span><strong>正在读取用户列表</strong></div>';
    }
    if (!state.users.length) {
      return '<div class="empty-state"><div><h3>暂无其他账户</h3><p>当前账户信息可在右上角查看。</p></div></div>';
    }
    return '<section class="panel"><div class="panel-head"><div class="panel-title"><h2>账户与权限</h2><p>' + state.users.length + ' 个本地账户 · 管理员可调整交易权限</p></div>' +
      '<span class="tag neutral">LOCAL ACCOUNTS</span></div>' +
      '<div class="table-wrap"><table class="stock-table user-table"><thead><tr><th>账户</th><th>角色</th><th>注册方式</th><th>最近登录</th><th>交易权限</th></tr></thead><tbody>' +
      state.users.map(function (user) {
        return '<tr><td><div class="user-cell"><span class="user-avatar">' + escape((user.display_name || user.username).slice(0, 1).toUpperCase()) + '</span>' +
          '<div class="stock-main"><strong>' + escape(user.display_name || user.username) + '</strong><span>' + escape(user.username) + '</span></div></div></td>' +
          '<td><span class="user-role-tag ' + (user.role === "owner" ? "owner" : "") + '">' + (user.role === "owner" ? "管理员" : "交易员") + '</span></td>' +
          '<td>' + escape(user.auth_provider === "local" ? "本地密码" : user.auth_provider) + '</td>' +
          '<td>' + (user.last_login_at ? timeText(user.last_login_at, true) : "—") + '</td>' +
          '<td><button class="switch ' + (user.trading_enabled ? "on" : "") + '" type="button" role="switch" aria-checked="' + user.trading_enabled + '" data-user-trading="' + escape(user.id) + '" data-enabled="' + user.trading_enabled + '"></button></td></tr>';
      }).join("") + '</tbody></table></div></section>';
  }

  function renderRisk() {
    var settings = state.data.settings;
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("单票上限", number(settings.max_position_pct, 0) + "%", "限制集中度", "shield", true) +
        statCard("止损线", number(settings.stop_loss_pct, 0) + "%", "单笔最大回撤", "chart") +
        statCard("单日亏损", number(settings.daily_loss_pct, 0) + "%", "触发后降低风险偏好", "pulse") +
        statCard("最低置信度", number(settings.min_confidence * 100, 0) + "%", "低于阈值保持观察", "lock") +
      '</div>' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>风控参数</h2><p>参数用于解释和约束量化决策，不构成自动下单指令</p></div>' +
          '<span class="tag ' + riskTagClass(state.data.overview.risk_level) + '">' + riskLabel(state.data.overview.risk_level) + '</span></div>' +
        '<form id="risk-form">' +
          '<div class="settings-grid">' +
            fieldNumber("max_position_pct", "单票仓位上限", settings.max_position_pct, "%", "0.1", "100") +
            fieldNumber("stop_loss_pct", "止损比例", settings.stop_loss_pct, "%", "0.1", "50") +
            fieldNumber("daily_loss_pct", "单日亏损阈值", settings.daily_loss_pct, "%", "0.1", "30") +
            fieldNumber("min_confidence", "最低置信度", Math.round(settings.min_confidence * 100), "%", "0", "100") +
          '</div>' +
          '<div class="settings-summary"><p>系统建议：风险偏好为「' + riskLabel(state.data.overview.risk_level) + '」时，减少追高动作并优先保留现金仓位。</p>' +
            '<button class="button button-primary" type="submit">保存风控配置</button></div>' +
        '</form>' +
      '</section>' +
    '</div>';
  }

  function renderHistory() {
    return '<section class="panel">' +
      '<div class="panel-head"><div class="panel-title"><h2>完整决策记录</h2><p>最新 ' + state.data.decisions.length + ' 条 · 最多保留 500 条</p></div>' +
        '<span class="tag neutral">' + escape(state.data.overview.data_source) + '</span></div>' +
      renderDecisionList(state.data.decisions, false) +
    '</section>';
  }

  function renderAgents() {
    var rows = state.data.agents.map(function (agent) {
      return '<div class="agent-item">' +
        '<span class="agent-icon"><svg><use href="#i-robot"></use></svg></span>' +
        '<div class="agent-copy"><strong>' + escape(agent.name) + ' · ' + escape(agent.role) + '</strong><p>' + escape(agent.detail) + '</p></div>' +
        '<span class="agent-state ' + (agent.status === "running" ? "" : "degraded") + '">' + (agent.status === "running" ? "运行中" : "降级") + '</span>' +
      '</div>';
    }).join("");
    return '<div class="view-stack">' +
      '<div class="stat-grid">' +
        statCard("模块在线", state.data.agents.filter(function (a) { return a.status === "running"; }).length + " / " + state.data.agents.length, "行情、量化、风控、记忆、接口", "robot", true) +
        statCard("行情源", state.data.overview.live_market ? "实时" : "降级", state.data.overview.data_source, "pulse") +
        statCard("决策记录", state.data.overview.decision_count, "本地持久化", "audit") +
        statCard("策略启用", state.data.strategies.filter(function (s) { return s.enabled; }).length, "参与下一次评分", "sliders") +
      '</div>' +
      '<section class="panel"><div class="panel-head"><div class="panel-title"><h2>运行模块</h2><p>Go 进程内的确定性模块，不依赖 Python Agent 运行时</p></div></div>' +
        '<div class="agent-list">' + rows + '</div></section>' +
    '</div>';
  }

  function renderSystem() {
    var data = state.data;
    return '<div class="view-stack">' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>服务信息</h2><p>单二进制部署 · Web 资源已内嵌</p></div><span class="tag low">Go ' + escape(data.version || "2.1.0") + '</span></div>' +
        '<div class="system-grid">' +
          '<div class="system-block"><h3>运行参数</h3>' +
            kv("服务语言", "Go") +
            kv("HTTP 框架", "net/http") +
            kv("行情源", data.overview.data_source) +
            kv("交易模式", data.trading.mode === "live" ? "实盘" : "模拟盘") +
            kv("券商通道", data.trading.broker) +
            kv("最近刷新", timeText(data.generated_at)) +
            kv("自选数量", String(data.overview.watch_count)) +
          '</div>' +
          '<div class="system-block"><h3>安全与持久化</h3>' +
            kv("会话保护", "SameSite=Strict · HttpOnly") +
            kv("密码存储", "Argon2id 加盐") +
            kv("注册开关", data.current_user ? "由服务端配置控制" : "—") +
            kv("请求体限制", "1 MiB") +
            kv("状态文件", "data/go/state.json") +
            kv("审计上限", "1000 条") +
            kv("部署端口", "19377") +
          '</div>' +
        '</div>' +
        '<div class="settings-summary"><p>Go 版本将行情、指标、风控、API 与前端资源打入同一容器；原有 Python 代码保留用于回滚与结果对照。</p>' +
          '<button class="button button-secondary" type="button" id="logout-button">退出登录</button></div>' +
      '</section>' +
      '<section class="panel">' +
        '<div class="panel-head"><div class="panel-title"><h2>账户安全</h2><p>本地账户使用 Argon2id 加盐哈希；扫码账户也可以设置本地备用密码</p></div>' +
          '<span class="mode-badge">' + escape((data.current_user && data.current_user.auth_provider === "local") ? "LOCAL" : "EXTERNAL") + '</span></div>' +
        '<form id="password-form">' +
          '<div class="settings-grid">' +
            '<label class="field"><span>当前密码 <em>扫码账户可留空</em></span><input class="input" name="current_password" type="password" autocomplete="current-password"></label>' +
            '<label class="field"><span>新密码</span><input class="input" name="new_password" type="password" minlength="10" maxlength="128" autocomplete="new-password" required></label>' +
          '</div>' +
          '<div class="settings-summary"><p>新密码至少 10 位，并同时包含字母和数字。</p>' +
            '<button class="button button-primary" type="submit">更新密码</button></div>' +
        '</form>' +
      '</section>' +
    '</div>';
  }

  function renderRail() {
    if (!state.data) {
      return;
    }
    var stocks = state.data.stocks.filter(function (stock) {
      if (!state.railSearch) {
        return true;
      }
      var haystack = (stock.name + " " + stock.symbol + " " + stock.notes).toLowerCase();
      return haystack.indexOf(state.railSearch.toLowerCase()) !== -1;
    });
    document.getElementById("rail-count").textContent = String(state.data.stocks.length);
    document.getElementById("rail-updated").textContent = "更新于 " + timeText(state.data.generated_at);
    if (!stocks.length) {
      watchList.innerHTML = '<div class="rail-loading">没有匹配的股票</div>';
      return;
    }
    watchList.innerHTML = stocks.map(function (stock) {
      var active = state.analysis && state.analysis.symbol === stock.symbol;
      return '<button class="watch-item' + (active ? " active" : "") + '" type="button" data-watch-symbol="' + escape(stock.symbol) + '">' +
        stockAvatar(stock.name || stock.symbol, "stock-avatar") +
        '<span class="watch-copy"><span class="watch-name"><span>' + escape(stock.name || stock.symbol) + '</span></span>' +
          '<span class="watch-code">' + escape(stock.symbol) + (stock.notes ? '<span class="watch-note">' + escape(stock.notes) + '</span>' : "") + '</span></span>' +
        '<span class="watch-price"><strong>' + money(stock.price) + '</strong><span class="' + changeClass(stock.change_pct) + '">' + changeText(stock.change_pct) + '</span></span>' +
      '</button>';
    }).join("");
  }

  function renderStockTable(stocks) {
    if (!stocks.length) {
      return '<div class="empty-state"><div><span class="empty-icon"><svg><use href="#i-search"></use></svg></span>' +
        '<h3>没有匹配的股票</h3><p>调整搜索条件，或添加一只新的自选股票。</p></div></div>';
    }
    var rows = stocks.map(function (stock) {
      return '<tr>' +
        '<td><div class="stock-cell">' + stockAvatar(stock.name || stock.symbol, "stock-avatar") +
          '<div class="stock-main"><strong>' + escape(stock.name || stock.symbol) + '</strong><span>' + escape(stock.symbol) + (stock.notes ? " · " + escape(stock.notes) : "") + '</span></div></div></td>' +
        '<td class="price-cell"><strong>' + money(stock.price) + '</strong><span class="' + changeClass(stock.change_pct) + '">' + changeText(stock.change_pct) + '</span></td>' +
        '<td>' + (stock.score === null ? '<span class="tag neutral">待分析</span>' : '<div class="score-wrap"><span>' + stock.score + '</span><span class="score-bar"><i style="width:' + stock.score + '%"></i></span></div>') + '</td>' +
        '<td>' + actionTag(stock.action) + '</td>' +
        '<td>' + riskTag(stock.risk) + '</td>' +
        '<td>' + escape(stock.updated_at ? timeText(stock.updated_at, true) : "—") + '</td>' +
        '<td><div class="actions-cell">' +
          '<button class="small-action" type="button" data-analyze-symbol="' + escape(stock.symbol) + '">诊股<svg><use href="#i-arrow"></use></svg></button>' +
          '<button class="small-action danger" type="button" data-delete-symbol="' + escape(stock.symbol) + '" aria-label="移除 ' + escape(stock.name || stock.symbol) + '"><svg><use href="#i-trash"></use></svg></button>' +
        '</div></td>' +
      '</tr>';
    }).join("");
    return '<div class="table-wrap"><table class="stock-table"><thead><tr>' +
      '<th>股票</th><th>最新价</th><th>评分</th><th>结论</th><th>风险</th><th>行情时间</th><th style="text-align:right">操作</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  function renderIndexGrid(indices) {
    if (!indices.length) {
      return '<div class="empty-state" style="min-height:160px"><div><h3>指数行情暂不可用</h3><p>保留空值，不使用模拟点位。</p></div></div>';
    }
    return '<div class="index-grid">' + indices.map(function (index) {
      return '<div class="index-item"><div class="index-name">' + escape(index.name) + '</div>' +
        '<div class="index-price">' + money(index.price) + '</div>' +
        '<div class="index-change ' + changeClass(index.change_pct) + '">' + changeText(index.change_pct) + '</div></div>';
    }).join("") + '</div>';
  }

  function renderDecisionList(decisions, compact) {
    if (!decisions.length) {
      return '<div class="empty-state"><div><span class="empty-icon"><svg><use href="#i-pulse"></use></svg></span><h3>还没有决策记录</h3><p>完成一次智能诊股后，结论会出现在这里。</p></div></div>';
    }
    return '<div class="decision-list">' + decisions.map(function (decision) {
      return '<div class="decision-item">' +
        '<span class="decision-mark"><svg><use href="#i-chart"></use></svg></span>' +
        '<div class="decision-copy"><strong>' + escape(decision.name) + ' <span class="tag ' + actionClass(decision.action) + '">' + actionLabel(decision.action) + '</span></strong>' +
          '<p>' + escape(decision.summary) + '</p></div>' +
        '<div class="decision-side"><strong>' + decision.score + ' 分 · ' + number(decision.confidence * 100, 0) + '%</strong><span>' + (compact ? timeText(decision.created_at, true) : actionLabel(decision.action) + " · 风险 " + escape(decision.risk)) + '</span></div>' +
      '</div>';
    }).join("") + '</div>';
  }

  function renderAuditList(audits) {
    if (!audits.length) {
      return '<div class="empty-state"><div><h3>暂无审计事件</h3><p>页面操作会自动写入不可变更的时间线。</p></div></div>';
    }
    return '<div class="audit-list">' + audits.map(function (audit) {
      return '<div class="audit-item"><div class="audit-action">' + escape(audit.action) + '</div>' +
        '<div class="audit-detail">' + escape(audit.detail) + '</div>' +
        '<div class="audit-time">' + timeText(audit.created_at, true) + '</div></div>';
    }).join("") + '</div>';
  }

  function filteredStocks(stocks) {
    return stocks.filter(function (stock) {
      if (state.search) {
        var haystack = (stock.name + " " + stock.symbol + " " + stock.notes).toLowerCase();
        if (haystack.indexOf(state.search.toLowerCase()) === -1) {
          return false;
        }
      }
      if (state.stockFilter === "up") {
        return stock.change_pct !== null && stock.change_pct > 0;
      }
      if (state.stockFilter === "down") {
        return stock.change_pct !== null && stock.change_pct < 0;
      }
      if (state.stockFilter === "analyzed") {
        return stock.score !== null;
      }
      return true;
    });
  }

  function statCard(label, value, foot, icon, accent) {
    return '<article class="stat-card' + (accent ? " accent" : "") + '">' +
      '<div class="stat-label"><span>' + escape(label) + '</span><svg><use href="#i-' + icon + '"></use></svg></div>' +
      '<div class="stat-value">' + escape(String(value)) + '</div>' +
      '<div class="stat-foot">' + escape(foot) + '</div>' +
    '</article>';
  }

  function filterButton(key, label) {
    return '<button type="button" class="' + (state.stockFilter === key ? "active" : "") + '" data-stock-filter="' + key + '">' + escape(label) + '</button>';
  }

  function verdict(label, value) {
    return '<div class="verdict-cell"><span>' + escape(label) + '</span><strong>' + escape(String(value)) + '</strong></div>';
  }

  function kv(label, value) {
    return '<div class="kv"><span>' + escape(label) + '</span><strong>' + escape(String(value)) + '</strong></div>';
  }

  function fieldNumber(name, label, value, suffix, min, max) {
    return '<label class="field"><span>' + escape(label) + ' <em>' + suffix + '</em></span>' +
      '<input name="' + escape(name) + '" type="number" value="' + escape(String(value)) + '" min="' + min + '" max="' + max + '" step="0.1" required>' +
    '</label>';
  }

  function indicatorPair(first, second) {
    return indicator(first) + " / " + indicator(second);
  }

  function indicator(value, digits) {
    if (value === null || value === undefined) {
      return "—";
    }
    return number(value, digits === undefined ? 2 : digits);
  }

  function sparkChart(bars) {
    if (!bars || bars.length < 2) {
      return '<div class="empty-state" style="min-height:110px"><div><p>K 线数据不足，无法绘图。</p></div></div>';
    }
    var width = 600;
    var height = 128;
    var padX = 4;
    var padY = 10;
    var values = bars.map(function (bar) { return bar.close; });
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    var span = max - min || 1;
    var points = values.map(function (value, index) {
      var x = padX + (index / (values.length - 1)) * (width - padX * 2);
      var y = padY + ((max - value) / span) * (height - padY * 2 - 12);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    var line = points.join(" ");
    var area = "M" + points[0] + " L" + points.slice(1).join(" L") + " L" + (width - padX) + "," + (height - 8) + " L" + padX + "," + (height - 8) + " Z";
    var grid = [0.25, 0.5, 0.75].map(function (ratio) {
      var y = padY + ratio * (height - padY * 2 - 12);
      return '<line class="grid-line" x1="0" y1="' + y.toFixed(1) + '" x2="' + width + '" y2="' + y.toFixed(1) + '"></line>';
    }).join("");
    return '<svg class="spark-chart" viewBox="0 0 600 128" preserveAspectRatio="none" role="img" aria-label="近 80 日收盘走势图">' +
      '<defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#1da7a2" stop-opacity=".18"></stop><stop offset="100%" stop-color="#1da7a2" stop-opacity="0"></stop></linearGradient></defs>' +
      grid + '<path class="price-area" d="' + area + '"></path><polyline class="price-line" points="' + line + '"></polyline></svg>';
  }

  function stockAvatar(name, className) {
    var palettes = [
      ["#dcefed", "#2c6f66"],
      ["#f5e4df", "#8f5a46"],
      ["#f8e2e8", "#9e4f62"],
      ["#e6e9f5", "#52658b"],
      ["#e6f0dc", "#557644"],
      ["#f2ead9", "#816431"]
    ];
    var hash = 0;
    for (var i = 0; i < name.length; i++) {
      hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    }
    var palette = palettes[hash % palettes.length];
    var text = name.slice(0, 2);
    return '<span class="' + className + '" style="--avatar-bg:' + palette[0] + ';--avatar-ink:' + palette[1] + '">' + escape(text) + '</span>';
  }

  function actionClass(action) {
    return action === "BUY" ? "buy" : action === "SELL" ? "sell" : "hold";
  }

  function actionTag(action) {
    return '<span class="tag ' + (action === "待分析" ? "neutral" : actionClass(action)) + '">' + actionLabel(action) + '</span>';
  }

  function actionLabel(action) {
    return {BUY: "买入关注", SELL: "减仓回避", HOLD: "持仓观望"}[action] || action || "待分析";
  }

  function riskTag(risk) {
    if (risk === "高") {
      return '<span class="tag high">高</span>';
    }
    if (risk === "中高") {
      return '<span class="tag medium">中高</span>';
    }
    if (risk === "中") {
      return '<span class="tag hold">中</span>';
    }
    if (risk === "中低") {
      return '<span class="tag low">中低</span>';
    }
    return '<span class="tag neutral">' + escape(risk || "未评估") + '</span>';
  }

  function riskTagClass(level) {
    return level === "low" ? "low" : level === "high" ? "high" : "medium";
  }

  function riskLabel(level) {
    return {low: "低风险", medium: "中等风险", high: "高风险", unknown: "待评估"}[level] || level || "待评估";
  }

  function changeClass(value) {
    if (value === null || value === undefined) {
      return "flat";
    }
    if (value > 0) {
      return "up";
    }
    if (value < 0) {
      return "down";
    }
    return "flat";
  }

  function changeText(value) {
    if (value === null || value === undefined) {
      return "—";
    }
    var sign = value > 0 ? "+" : "";
    return sign + number(value, 2) + "%";
  }

  function money(value) {
    if (value === null || value === undefined) {
      return "—";
    }
    return number(value, 2);
  }

  function signedMoney(value) {
    if (value === null || value === undefined) {
      return "—";
    }
    return (Number(value) > 0 ? "+" : "") + number(value, 2);
  }

  function signedPercent(value) {
    if (value === null || value === undefined) {
      return "—";
    }
    return (Number(value) > 0 ? "+" : "") + number(value, 2) + "%";
  }

  function orderStatusLabel(status) {
    return {
      FILLED: "已成交",
      PENDING: "待成交",
      CANCELED: "已撤单",
      REJECTED: "已拒绝",
      SUBMITTED: "已提交",
      PARTIALLY_FILLED: "部分成交"
    }[status] || status || "—";
  }

  function number(value, digits) {
    var numeric = Number(value);
    if (!isFinite(numeric)) {
      return "—";
    }
    return numeric.toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function timeText(value, withSeconds) {
    if (!value) {
      return "—";
    }
    var date = new Date(value);
    if (isNaN(date.getTime())) {
      return "—";
    }
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: withSeconds ? "2-digit" : undefined,
      hour12: false
    });
  }

  function escape(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function errorState(heading, detail) {
    return '<div class="empty-state"><div><span class="empty-icon"><svg><use href="#i-pulse"></use></svg></span>' +
      '<h3>' + escape(heading) + '</h3><p>' + escape(detail) + '</p></div></div>';
  }

  function showToast(message, isError) {
    clearTimeout(state.toastTimer);
    toast.textContent = message;
    toast.classList.toggle("error", Boolean(isError));
    toast.classList.add("show");
    state.toastTimer = setTimeout(function () {
      toast.classList.remove("show");
    }, 3200);
  }

  function setView(view) {
    if (!VIEWS[view]) {
      return;
    }
    state.view = view;
    document.querySelectorAll(".nav-item").forEach(function (item) {
      var active = item.getAttribute("data-view") === view;
      item.classList.toggle("active", active);
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });
    closeMobileRail();
    renderHeader();
    renderView();
    if (view === "users") {
      loadUsers();
    }
  }

  function loadUsers() {
    state.usersLoaded = false;
    renderView();
    api("/api/v1/users").then(function (payload) {
      state.users = payload.items || [];
      state.usersLoaded = true;
      renderView();
    }).catch(function (error) {
      state.usersLoaded = true;
      state.users = [];
      renderView();
      showToast(error.message, true);
    });
  }

  function openStockDialog() {
    stockForm.reset();
    stockFormError.hidden = true;
    if (typeof stockDialog.showModal === "function") {
      stockDialog.showModal();
    } else {
      stockDialog.setAttribute("open", "");
    }
    setTimeout(function () {
      document.getElementById("stock-symbol").focus();
    }, 30);
  }

  function closeStockDialog() {
    if (typeof stockDialog.close === "function") {
      stockDialog.close();
    } else {
      stockDialog.removeAttribute("open");
    }
  }

  function analyzeSymbol(symbol) {
    state.view = "analyze";
    state.analysis = null;
    document.querySelectorAll(".nav-item").forEach(function (item) {
      var active = item.getAttribute("data-view") === "analyze";
      item.classList.toggle("active", active);
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });
    renderHeader();
    viewRoot.innerHTML = '<div class="loading-state"><span class="loading-ring"></span><strong>正在分析 ' + escape(symbol) + '</strong><small>读取 K 线并计算技术指标…</small></div>';
    api("/api/v1/analyze", {method: "POST", body: {symbol: symbol}}).then(function (analysis) {
      state.analysis = analysis;
      renderView();
      renderRail();
      showToast(analysis.name + " 分析完成");
    }).catch(function (error) {
      renderView();
      showToast(error.message, true);
    });
  }

  function removeStock(symbol) {
    var stock = state.data.stocks.find(function (item) { return item.symbol === symbol; });
    var name = stock ? stock.name : symbol;
    if (!window.confirm("确定从自选名单移除 " + name + "？历史决策会保留。")) {
      return;
    }
    api("/api/v1/stocks/" + encodeURIComponent(symbol), {method: "DELETE"}).then(function () {
      showToast("已移除 " + name);
      return loadDashboard({silent: true});
    }).catch(function (error) {
      showToast(error.message, true);
    });
  }

  function toggleStrategy(button) {
    var key = button.getAttribute("data-strategy");
    var enabled = button.getAttribute("data-enabled") !== "true";
    button.disabled = true;
    api("/api/v1/strategies/" + encodeURIComponent(key) + "/toggle", {
      method: "POST",
      body: {enabled: enabled}
    }).then(function () {
      button.setAttribute("data-enabled", String(enabled));
      button.setAttribute("aria-checked", String(enabled));
      button.classList.toggle("on", enabled);
      showToast(enabled ? "策略已启用" : "策略已停用");
      return loadDashboard({silent: true});
    }).catch(function (error) {
      showToast(error.message, true);
    }).finally(function () {
      button.disabled = false;
    });
  }

  function placeOrder(form) {
    var data = new FormData(form);
    var orderType = String(data.get("order_type") || "MARKET");
    var limitPrice = orderType === "LIMIT" ? Number(data.get("limit_price")) : null;
    if (orderType === "LIMIT" && (!limitPrice || limitPrice <= 0)) {
      showToast("限价委托需要填写有效价格", true);
      return;
    }
    var submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    api("/api/v1/trading/orders", {
      method: "POST",
      body: {
        client_order_id: clientOrderID(),
        symbol: String(data.get("symbol") || "").trim(),
        side: state.tradeSide,
        order_type: orderType,
        quantity: Number(data.get("quantity")),
        limit_price: limitPrice,
        reason: String(data.get("reason") || "").trim()
      }
    }).then(function (order) {
      showToast(orderStatusLabel(order.status) + " · " + (order.name || order.symbol));
      return loadDashboard({silent: true});
    }).catch(function (error) {
      showToast(error.message, true);
    }).finally(function () {
      submit.disabled = false;
    });
  }

  function cancelOrder(orderID) {
    if (!window.confirm("确认撤销这笔待成交委托？")) {
      return;
    }
    api("/api/v1/trading/orders/" + encodeURIComponent(orderID) + "/cancel", {method: "POST"})
      .then(function () {
        showToast("撤单请求已提交");
        return loadDashboard({silent: true});
      }).catch(function (error) {
        showToast(error.message, true);
      });
  }

  function custodyFromForm(form) {
    var data = new FormData(form);
    return {
      enabled: Boolean(state.data.custody && state.data.custody.enabled),
      symbols: String(data.get("symbols") || "").split(/[\s,，]+/).filter(Boolean),
      buy_score: Number(data.get("buy_score")),
      sell_score: Number(data.get("sell_score")),
      min_confidence: Number(data.get("min_confidence")) / 100,
      max_order_value: Number(data.get("max_order_value")),
      interval_seconds: Number(data.get("interval_seconds")),
      allow_buy: data.get("allow_buy") === "on",
      allow_sell: data.get("allow_sell") === "on"
    };
  }

  function saveCustody(form) {
    var submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    api("/api/v1/custody", {method: "PUT", body: custodyFromForm(form)})
      .then(function () {
        showToast("托管参数已保存");
        return loadDashboard({silent: true});
      }).catch(function (error) {
        showToast(error.message, true);
      }).finally(function () {
        submit.disabled = false;
      });
  }

  function toggleCustody(enabled) {
    var form = document.getElementById("custody-form");
    if (!form) {
      return;
    }
    var confirmation = "";
    if (enabled) {
      confirmation = window.prompt("托管交易会自动提交订单。请输入 ENABLE CUSTODY 确认开启：");
      if (confirmation === null) {
        return;
      }
    }
    var payload = custodyFromForm(form);
    payload.enabled = enabled;
    payload.confirmation = confirmation;
    api("/api/v1/custody", {method: "PUT", body: payload})
      .then(function () {
        showToast(enabled ? "托管交易已开启" : "托管交易已停止");
        return loadDashboard({silent: true});
      }).catch(function (error) {
        showToast(error.message, true);
      });
  }

  function runCustody() {
    var force = state.data.trading.mode !== "live";
    api("/api/v1/custody/run", {method: "POST", body: {force: force}})
      .then(function (payload) {
        showToast("托管检查完成，提交 " + payload.count + " 笔委托");
        return loadDashboard({silent: true});
      }).catch(function (error) {
        showToast(error.message, true);
      });
  }

  function toggleUserTrading(button) {
    var enabled = button.getAttribute("data-enabled") !== "true";
    button.disabled = true;
    api("/api/v1/users/" + encodeURIComponent(button.getAttribute("data-user-trading")) + "/trading", {
      method: "POST",
      body: {enabled: enabled}
    }).then(function () {
      showToast(enabled ? "交易权限已开启" : "交易权限已关闭");
      state.usersLoaded = false;
      loadUsers();
      return loadDashboard({silent: true});
    }).catch(function (error) {
      showToast(error.message, true);
    }).finally(function () {
      button.disabled = false;
    });
  }

  function clientOrderID() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return "web-" + window.crypto.randomUUID();
    }
    return "web-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }

  function closeMobileRail() {
    document.body.classList.remove("rail-open");
  }

  function logout() {
    fetch("/api/v1/auth/logout", {method: "POST", credentials: "same-origin"})
      .finally(function () { location.assign("/login"); });
  }

  function bindEvents() {
    document.querySelectorAll(".nav-item").forEach(function (item) {
      item.addEventListener("click", function (event) {
        event.preventDefault();
        setView(item.getAttribute("data-view"));
      });
    });

    document.getElementById("global-search").addEventListener("input", function (event) {
      state.search = event.target.value.trim();
      if (state.view === "stocks" || state.view === "portfolio") {
        renderView();
      }
    });

    document.getElementById("rail-search").addEventListener("input", function (event) {
      state.railSearch = event.target.value.trim();
      renderRail();
    });

    document.getElementById("refresh-button").addEventListener("click", function () {
      loadDashboard().then(function () {
        showToast("行情与决策记录已刷新");
      });
    });

    document.getElementById("add-stock-button").addEventListener("click", openStockDialog);
    document.getElementById("rail-add-button").addEventListener("click", openStockDialog);
    document.getElementById("menu-button").addEventListener("click", function () {
      document.body.classList.toggle("rail-open");
    });
    document.getElementById("rail-backdrop").addEventListener("click", closeMobileRail);
    document.getElementById("header-logout").addEventListener("click", logout);

    document.querySelectorAll("[data-close-dialog]").forEach(function (button) {
      button.addEventListener("click", closeStockDialog);
    });

    stockDialog.addEventListener("click", function (event) {
      if (event.target === stockDialog) {
        closeStockDialog();
      }
    });

    stockForm.addEventListener("submit", function (event) {
      event.preventDefault();
      stockFormError.hidden = true;
      var submit = stockForm.querySelector('button[type="submit"]');
      submit.disabled = true;
      api("/api/v1/stocks", {
        method: "POST",
        body: {
          symbol: document.getElementById("stock-symbol").value.trim(),
          name: document.getElementById("stock-name").value.trim(),
          notes: document.getElementById("stock-notes").value.trim()
        }
      }).then(function () {
        closeStockDialog();
        showToast("已加入自选名单");
        return loadDashboard({silent: true});
      }).catch(function (error) {
        stockFormError.textContent = error.message;
        stockFormError.hidden = false;
      }).finally(function () {
        submit.disabled = false;
      });
    });

    viewRoot.addEventListener("click", function (event) {
      var target = event.target.closest("button, [data-go-view]");
      if (!target) {
        return;
      }
      if (target.hasAttribute("data-open-stock")) {
        openStockDialog();
        return;
      }
      if (target.hasAttribute("data-go-view")) {
        setView(target.getAttribute("data-go-view"));
        return;
      }
      if (target.hasAttribute("data-stock-filter")) {
        state.stockFilter = target.getAttribute("data-stock-filter");
        renderView();
        return;
      }
      if (target.hasAttribute("data-analyze-symbol")) {
        analyzeSymbol(target.getAttribute("data-analyze-symbol"));
        return;
      }
      if (target.hasAttribute("data-delete-symbol")) {
        removeStock(target.getAttribute("data-delete-symbol"));
        return;
      }
      if (target.hasAttribute("data-strategy")) {
        toggleStrategy(target);
        return;
      }
      if (target.hasAttribute("data-trade-side")) {
        state.tradeSide = target.getAttribute("data-trade-side");
        renderView();
        return;
      }
      if (target.hasAttribute("data-cancel-order")) {
        cancelOrder(target.getAttribute("data-cancel-order"));
        return;
      }
      if (target.hasAttribute("data-custody-toggle")) {
        toggleCustody(target.getAttribute("data-custody-toggle") === "on");
        return;
      }
      if (target.hasAttribute("data-custody-run")) {
        runCustody();
        return;
      }
      if (target.hasAttribute("data-user-trading")) {
        toggleUserTrading(target);
        return;
      }
      if (target.hasAttribute("data-open-trade")) {
        loadDashboard();
        return;
      }
      if (target.id === "logout-button") {
        logout();
      }
    });

    viewRoot.addEventListener("change", function (event) {
      if (event.target.id === "order-type") {
        var limitField = document.getElementById("limit-price-field");
        if (limitField) {
          limitField.hidden = event.target.value !== "LIMIT";
        }
      }
    });

    viewRoot.addEventListener("submit", function (event) {
      if (event.target.id === "analyze-form") {
        event.preventDefault();
        var symbol = document.getElementById("analyze-symbol").value.trim();
        if (symbol) {
          analyzeSymbol(symbol);
        }
        return;
      }
      if (event.target.id === "risk-form") {
        event.preventDefault();
        var data = new FormData(event.target);
        var submit = event.target.querySelector('button[type="submit"]');
        submit.disabled = true;
        api("/api/v1/settings", {
          method: "PUT",
          body: {
            max_position_pct: Number(data.get("max_position_pct")),
            stop_loss_pct: Number(data.get("stop_loss_pct")),
            daily_loss_pct: Number(data.get("daily_loss_pct")),
            min_confidence: Number(data.get("min_confidence")) / 100
          }
        }).then(function () {
          showToast("风控配置已保存");
          return loadDashboard({silent: true});
        }).catch(function (error) {
          showToast(error.message, true);
        }).finally(function () {
          submit.disabled = false;
        });
        return;
      }
      if (event.target.id === "order-form") {
        event.preventDefault();
        placeOrder(event.target);
        return;
      }
      if (event.target.id === "custody-form") {
        event.preventDefault();
        saveCustody(event.target);
        return;
      }
      if (event.target.id === "password-form") {
        event.preventDefault();
        var passwordData = new FormData(event.target);
        var passwordSubmit = event.target.querySelector('button[type="submit"]');
        passwordSubmit.disabled = true;
        api("/api/v1/auth/password", {
          method: "POST",
          body: {
            current_password: String(passwordData.get("current_password") || ""),
            new_password: String(passwordData.get("new_password") || "")
          }
        }).then(function () {
          event.target.reset();
          showToast("密码已更新");
        }).catch(function (error) {
          showToast(error.message, true);
        }).finally(function () {
          passwordSubmit.disabled = false;
        });
      }
    });

    watchList.addEventListener("click", function (event) {
      var button = event.target.closest("[data-watch-symbol]");
      if (button) {
        analyzeSymbol(button.getAttribute("data-watch-symbol"));
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeMobileRail();
        if (stockDialog.open) {
          closeStockDialog();
        }
      }
    });
  }

  bindEvents();
  loadDashboard();
  setInterval(function () {
    if (!document.hidden) {
      loadDashboard({silent: true});
    }
  }, 60000);
})();

