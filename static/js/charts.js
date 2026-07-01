/*
 * Market Trace V6.0 — Chart Module
 * 封装 lightweight-charts 的 K线图、成交量图、回测柱状图渲染。
 * 依赖: lightweight-charts@4 (CDN 加载，全局 LightweightCharts 对象)
 */

var Charts = (function() {
  'use strict';

  var _instances = {};

  var COLORS = {
    bg: '#161b22',
    text: '#8b949e',
    grid: 'rgba(48,54,61,0.5)',
    green: '#3fb950',
    red: '#f85149',
    rise: '#f85149',
    fall: '#3fb950',
    blue: '#58a6ff',
    purple: '#bc8cff',
    yellow: '#d29922',
    candleUpBorder: '#f85149',
    candleUpFill: 'rgba(248,81,73,0.25)',
    candleDownBorder: '#3fb950',
    candleDownFill: 'rgba(63,185,80,0.3)',
    volumeUp: 'rgba(248,81,73,0.35)',
    volumeDown: 'rgba(63,185,80,0.4)',
  };

  function _baseOptions(height) {
    return {
      width: 0,
      height: height || 320,
      layout: {
        background: { type: 'solid', color: COLORS.bg },
        textColor: COLORS.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: COLORS.blue, style: 2, width: 1, labelBackgroundColor: COLORS.blue },
        horzLine: { color: COLORS.blue, style: 2, width: 1, labelBackgroundColor: COLORS.blue },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: COLORS.grid,
      },
      rightPriceScale: {
        borderColor: COLORS.grid,
        scaleMargins: { top: 0.02, bottom: 0.02 },
      },
    };
  }

  function _ensureLWC() {
    if (typeof LightweightCharts === 'undefined') {
      console.warn('lightweight-charts 未加载');
      return false;
    }
    return true;
  }

  function destroy(key) {
    if (_instances[key]) {
      try { _instances[key].chart.remove(); } catch(e) {}
      delete _instances[key];
    }
  }

  function destroyAll() {
    Object.keys(_instances).forEach(function(k) { destroy(k); });
  }

  /**
   * renderKline(containerId, data)
   * data.bars: [{time, open, high, low, close, volume}, ...]
   */
  function renderKline(containerId, data) {
    if (!_ensureLWC()) return;
    destroy(containerId);

    var bars = data && data.bars ? data.bars : data;
    if (!bars || !bars.length) return;

    var container = document.getElementById(containerId);
    if (!container) return;

    var W = container.clientWidth || container.parentElement.clientWidth - 32 || 600;
    var totalH = 380;
    var candleH = Math.floor(totalH * 0.7);
    var volumeH = totalH - candleH;

    var chartOpts = _baseOptions(totalH);
    chartOpts.width = W;
    chartOpts.height = totalH;

    var chart = LightweightCharts.createChart(container, chartOpts);

    var candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.candleUpBorder,
      downColor: COLORS.candleDownBorder,
      borderUpColor: COLORS.candleUpBorder,
      borderDownColor: COLORS.candleDownBorder,
      wickUpColor: COLORS.candleUpBorder,
      wickDownColor: COLORS.candleDownBorder,
      priceScaleId: 'right',
    });
    candleSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.05, bottom: 0.28 },
    });

    var volumeSeries = chart.addHistogramSeries({
      color: COLORS.volumeUp,
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0.02 },
    });

    var sorted = bars.slice().sort(function(a, b) {
      return (a.time || '').localeCompare(b.time || '');
    });

    var candleData = [];
    var volumeData = [];
    var colors = [];

    for (var i = 0; i < sorted.length; i++) {
      var b = sorted[i];
      var t = b.time;
      if (!t) continue;
      if (t.indexOf('T') !== -1) t = t.split('T')[0];
      candleData.push({ time: t, open: b.open, high: b.high, low: b.low, close: b.close });
      var isUp = b.close >= b.open;
      volumeData.push({ time: t, value: b.volume, color: isUp ? COLORS.volumeUp : COLORS.volumeDown });
    }

    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    chart.timeScale().fitContent();

    _instances[containerId] = { chart: chart };
  }

  /**
   * renderBacktestBars(containerId, data)
   * data: [{ label, sharpe, win_rate, max_drawdown, score }, ...]
   */
  function renderBacktestBars(containerId, data) {
    if (!_ensureLWC()) return;
    destroy(containerId);

    if (!data || !data.length) return;

    var container = document.getElementById(containerId);
    if (!container) return;

    var W = container.clientWidth || 500;
    var H = 260;

    var chartOpts = _baseOptions(H);
    chartOpts.width = W;
    chartOpts.height = H;
    chartOpts.rightPriceScale = { borderColor: COLORS.grid, scaleMargins: { top: 0.05, bottom: 0.05 } };

    var chart = LightweightCharts.createChart(container, chartOpts);

    var sharpeSeries = chart.addHistogramSeries({
      color: COLORS.blue,
      priceScaleId: 'right',
    });

    var winSeries = chart.addLineSeries({
      color: COLORS.green,
      priceScaleId: 'right',
      lineWidth: 2,
    });

    var timeData = [];
    var sharpeData = [];
    var winData = [];

    for (var i = 0; i < data.length; i++) {
      var label = data[i].label;
      timeData.push(i);
      sharpeData.push({ time: i, value: data[i].sharpe || 0 });
      winData.push({ time: i, value: (data[i].win_rate || 0) * 100 });
    }

    sharpeSeries.setData(sharpeData);
    winSeries.setData(winData);

    chart.timeScale().applyOptions({ visible: false });
    chart.timeScale().fitContent();

    _instances[containerId] = { chart: chart };
  }

  function renderEquityCurve(containerId, drawdownId, equityData, benchmarkData, drawdownData, markers) {
    if (!_ensureLWC()) return;
    destroy(containerId);
    destroy(drawdownId);

    if (!equityData || !equityData.length) return;

    var container = document.getElementById(containerId);
    if (!container) return;
    var W = container.clientWidth || 500;
    var H = 300;

    var chartOpts = _baseOptions(H);
    chartOpts.width = W;
    chartOpts.height = H;
    chartOpts.rightPriceScale = { borderColor: COLORS.grid, scaleMargins: { top: 0.05, bottom: 0.05 } };

    var chart = LightweightCharts.createChart(container, chartOpts);

    // 权益曲线
    var equitySeries = chart.addAreaSeries({
      lineColor: COLORS.blue,
      topColor: 'rgba(88,166,255,0.3)',
      bottomColor: 'rgba(88,166,255,0.02)',
      lineWidth: 2,
      priceScaleId: 'right',
    });
    var eqData = equityData.map(function(e) { return { time: e.time ? e.time.split('T')[0] : '', value: e.equity }; }).filter(function(e) { return e.time; });
    equitySeries.setData(eqData);

    // 基准曲线
    if (benchmarkData && benchmarkData.length) {
      var benchSeries = chart.addLineSeries({
        color: COLORS.text,
        lineWidth: 1,
        lineStyle: 2,
        priceScaleId: 'right',
      });
      var bmData = benchmarkData.map(function(e) { return { time: e.time ? e.time.split('T')[0] : '', value: e.value }; }).filter(function(e) { return e.time; });
      benchSeries.setData(bmData);
    }

    // 买卖标记
    if (markers && markers.length) {
      var markerData = markers.filter(function(m) { return m.time; }).map(function(m) {
        return {
          time: m.time.split('T')[0],
          position: m.type === 'buy' ? 'belowBar' : 'aboveBar',
          color: m.type === 'buy' ? COLORS.green : COLORS.red,
          shape: m.type === 'buy' ? 'arrowUp' : 'arrowDown',
          text: m.type === 'buy' ? 'B' : 'S',
          size: 2,
        };
      });
      equitySeries.setMarkers(markerData);
    }

    chart.timeScale().fitContent();
    _instances[containerId] = { chart: chart };

    // 回撤图
    if (drawdownData && drawdownData.length) {
      var ddContainer = document.getElementById(drawdownId);
      if (!ddContainer) return;
      var ddW = ddContainer.clientWidth || 500;
      var ddH = 120;

      var ddOpts = _baseOptions(ddH);
      ddOpts.width = ddW;
      ddOpts.height = ddH;
      ddOpts.rightPriceScale = { borderColor: COLORS.grid, scaleMargins: { top: 0.1, bottom: 0.1 } };

      var ddChart = LightweightCharts.createChart(ddContainer, ddOpts);

      var ddSeries = ddChart.addAreaSeries({
        lineColor: COLORS.red,
        topColor: 'rgba(248,81,73,0.3)',
        bottomColor: 'rgba(248,81,73,0.02)',
        lineWidth: 1,
        priceScaleId: 'right',
        priceFormat: { type: 'percent', precision: 1 },
      });
      var ddData = drawdownData.map(function(d) {
        return { time: d.time ? d.time.split('T')[0] : '', value: d.drawdown };
      }).filter(function(d) { return d.time; });
      ddSeries.setData(ddData);
      ddChart.timeScale().fitContent();
      _instances[drawdownId] = { chart: ddChart };
    }
  }

  return {
    renderKline: renderKline,
    renderBacktestBars: renderBacktestBars,
    renderEquityCurve: renderEquityCurve,
    destroy: destroy,
    destroyAll: destroyAll,
  };
})();
