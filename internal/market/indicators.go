package market

import (
	"fmt"
	"math"
	"sort"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

type analysisResult struct {
	Indicators domain.Indicators
	Signals    []domain.Signal
	Score      int
	Action     string
	Confidence float64
	Risk       string
	Summary    string
	Complete   bool
}

func analyzeBars(bars []domain.Bar, enabled map[string]bool) analysisResult {
	result := analysisResult{Score: 50, Action: "HOLD", Risk: "中", Signals: []domain.Signal{}}
	if len(bars) < 5 {
		result.Summary = "K 线数据不足，暂不生成交易方向。"
		result.Risk = "未知"
		return result
	}

	closes := make([]float64, len(bars))
	highs := make([]float64, len(bars))
	lows := make([]float64, len(bars))
	volumes := make([]float64, len(bars))
	for i, bar := range bars {
		closes[i] = bar.Close
		highs[i] = bar.High
		lows[i] = bar.Low
		volumes[i] = bar.Volume
	}
	last := len(bars) - 1
	price := closes[last]
	ind := &result.Indicators

	if value, ok := movingAverage(closes, 5); ok {
		ind.MA5 = floatPtr(value)
	}
	if value, ok := movingAverage(closes, 10); ok {
		ind.MA10 = floatPtr(value)
	}
	if value, ok := movingAverage(closes, 20); ok {
		ind.MA20 = floatPtr(value)
	}
	if value, ok := movingAverage(closes, 60); ok {
		ind.MA60 = floatPtr(value)
	}
	if value, ok := rsi(closes, 14); ok {
		ind.RSI14 = floatPtr(value)
	}
	if dif, dea, hist, ok := macd(closes, 12, 26, 9); ok {
		ind.MACD = floatPtr(dif)
		ind.MACDSignal = floatPtr(dea)
		ind.MACDHistogram = floatPtr(hist)
	}
	if value, ok := kdjK(highs, lows, closes, 9); ok {
		ind.KDJ = floatPtr(value)
	}
	if value, ok := atr(highs, lows, closes, 14); ok {
		ind.ATR14 = floatPtr(value)
	}
	if upper, middle, lower, ok := bollinger(closes, 20, 2); ok {
		ind.BollUpper = floatPtr(upper)
		ind.BollMiddle = floatPtr(middle)
		ind.BollLower = floatPtr(lower)
	}
	if last > 0 && len(volumes) >= 6 {
		avg := average(volumes[last-5 : last])
		if avg > 0 {
			ind.VolumeRatio = floatPtr(volumes[last] / avg)
		}
	}
	if len(highs) >= 21 {
		ind.Resistance = floatPtr(maxOf(highs[last-20 : last]))
		ind.Support = floatPtr(minOf(lows[last-20 : last]))
	}

	trendScore := 0
	if ind.MA5 != nil && ind.MA20 != nil {
		switch {
		case *ind.MA5 > *ind.MA20 && price > *ind.MA5:
			ind.Trend = "多头"
			trendScore = 12
		case *ind.MA5 < *ind.MA20 && price < *ind.MA5:
			ind.Trend = "空头"
			trendScore = -12
		default:
			ind.Trend = "震荡"
		}
	} else {
		ind.Trend = "数据不足"
	}
	result.Score += trendScore
	if trendScore > 0 {
		result.Signals = append(result.Signals, domain.Signal{
			Key: "trend", Label: "均线多头排列", Direction: "bullish", Strength: 0.62,
			Evidence: fmt.Sprintf("MA5 %.2f 高于 MA20 %.2f，现价位于短期均线上方", *ind.MA5, *ind.MA20),
		})
	} else if trendScore < 0 {
		result.Signals = append(result.Signals, domain.Signal{
			Key: "trend", Label: "均线空头排列", Direction: "bearish", Strength: 0.62,
			Evidence: fmt.Sprintf("MA5 %.2f 低于 MA20 %.2f，现价位于短期均线下方", *ind.MA5, *ind.MA20),
		})
	}

	if enabled["ma_cross"] && len(closes) >= 21 {
		prevShort, _ := movingAverage(closes[:last], 5)
		prevLong, _ := movingAverage(closes[:last], 20)
		if ind.MA5 != nil && ind.MA20 != nil {
			if prevShort <= prevLong && *ind.MA5 > *ind.MA20 {
				result.Score += 14
				result.Signals = append(result.Signals, domain.Signal{
					Key: "ma_cross", Label: "均线金叉", Direction: "bullish", Strength: 0.78,
					Evidence: "MA5 上穿 MA20，趋势由弱转强",
				})
			} else if prevShort >= prevLong && *ind.MA5 < *ind.MA20 {
				result.Score -= 14
				result.Signals = append(result.Signals, domain.Signal{
					Key: "ma_cross", Label: "均线死叉", Direction: "bearish", Strength: 0.78,
					Evidence: "MA5 下穿 MA20，短期趋势转弱",
				})
			}
		}
	}

	if ind.RSI14 != nil {
		switch {
		case *ind.RSI14 < 30:
			result.Score += 12
			result.Signals = append(result.Signals, domain.Signal{
				Key: "rsi_reversal", Label: "RSI 超卖", Direction: "bullish", Strength: 0.68,
				Evidence: fmt.Sprintf("RSI14 为 %.1f，进入超卖区间", *ind.RSI14),
			})
		case *ind.RSI14 > 72:
			result.Score -= 12
			result.Signals = append(result.Signals, domain.Signal{
				Key: "rsi_overbought", Label: "RSI 超买", Direction: "bearish", Strength: 0.68,
				Evidence: fmt.Sprintf("RSI14 为 %.1f，短线过热风险上升", *ind.RSI14),
			})
		}
	}

	if ind.MACDHistogram != nil && len(closes) >= 27 {
		_, _, prevHist, ok := macd(closes[:last], 12, 26, 9)
		if ok && enabled["macd_reversal"] {
			if prevHist <= 0 && *ind.MACDHistogram > 0 {
				result.Score += 10
				result.Signals = append(result.Signals, domain.Signal{
					Key: "macd_reversal", Label: "MACD 动能翻红", Direction: "bullish", Strength: 0.69,
					Evidence: "MACD 柱体由负转正，下跌动能衰减",
				})
			} else if prevHist >= 0 && *ind.MACDHistogram < 0 {
				result.Score -= 10
				result.Signals = append(result.Signals, domain.Signal{
					Key: "macd_reversal", Label: "MACD 动能转弱", Direction: "bearish", Strength: 0.69,
					Evidence: "MACD 柱体由正转负，上涨动能衰减",
				})
			}
		}
	}

	if ind.Resistance != nil && enabled["channel_breakout"] && price > *ind.Resistance {
		result.Score += 11
		result.Signals = append(result.Signals, domain.Signal{
			Key: "channel_breakout", Label: "近 20 日新高", Direction: "bullish", Strength: 0.74,
			Evidence: fmt.Sprintf("收盘价 %.2f 突破前 20 日高点 %.2f", price, *ind.Resistance),
		})
	}
	if ind.Support != nil && enabled["channel_breakout"] && price < *ind.Support {
		result.Score -= 11
		result.Signals = append(result.Signals, domain.Signal{
			Key: "channel_breakout", Label: "跌破近期支撑", Direction: "bearish", Strength: 0.74,
			Evidence: fmt.Sprintf("收盘价 %.2f 跌破前 20 日低点 %.2f", price, *ind.Support),
		})
	}

	if ind.VolumeRatio != nil && enabled["volume_breakout"] {
		dayChange := 0.0
		if len(closes) >= 2 && closes[last-1] != 0 {
			dayChange = (price - closes[last-1]) / closes[last-1] * 100
		}
		if *ind.VolumeRatio >= 1.8 && dayChange > 0 {
			result.Score += 9
			result.Signals = append(result.Signals, domain.Signal{
				Key: "volume_breakout", Label: "放量上行", Direction: "bullish", Strength: 0.71,
				Evidence: fmt.Sprintf("量比 %.2f，价量同步走强", *ind.VolumeRatio),
			})
		} else if *ind.VolumeRatio >= 1.8 && dayChange < 0 {
			result.Score -= 9
			result.Signals = append(result.Signals, domain.Signal{
				Key: "volume_breakout", Label: "放量下跌", Direction: "bearish", Strength: 0.71,
				Evidence: fmt.Sprintf("量比 %.2f，抛压明显放大", *ind.VolumeRatio),
			})
		}
	}

	if ind.BollLower != nil && price < *ind.BollLower {
		result.Score += 6
		result.Signals = append(result.Signals, domain.Signal{
			Key: "boll_lower", Label: "跌破布林下轨", Direction: "bullish", Strength: 0.55,
			Evidence: "价格跌出统计区间，存在技术性修复可能",
		})
	}
	if ind.BollUpper != nil && price > *ind.BollUpper {
		result.Score -= 6
		result.Signals = append(result.Signals, domain.Signal{
			Key: "boll_upper", Label: "突破布林上轨", Direction: "bearish", Strength: 0.55,
			Evidence: "价格偏离均值上沿，追高回撤风险增加",
		})
	}

	result.Score = clamp(result.Score, 0, 100)
	result.Complete = len(bars) >= 60 && ind.MA60 != nil
	switch {
	case result.Score >= 72:
		result.Action = "BUY"
	case result.Score <= 32:
		result.Action = "SELL"
	default:
		result.Action = "HOLD"
	}
	distance := math.Abs(float64(result.Score)-50) / 50
	result.Confidence = math.Round((0.52+distance*0.4)*100) / 100
	if result.Confidence > 0.92 {
		result.Confidence = 0.92
	}

	atrPct := 0.0
	if ind.ATR14 != nil && price > 0 {
		atrPct = *ind.ATR14 / price * 100
	}
	switch {
	case (ind.RSI14 != nil && *ind.RSI14 > 78) || atrPct > 4.5 || result.Score < 28:
		result.Risk = "高"
	case (ind.RSI14 != nil && *ind.RSI14 > 68) || atrPct > 2.8:
		result.Risk = "中高"
	default:
		result.Risk = "中"
	}
	if result.Complete && result.Risk == "中" && result.Score >= 50 && result.Score <= 65 {
		result.Risk = "中低"
	}
	result.Summary = decisionSummary(result.Action, ind.Trend, result.Signals, result.Risk)
	return result
}

func decisionSummary(action, trend string, signals []domain.Signal, risk string) string {
	positive, negative := 0, 0
	for _, signal := range signals {
		if signal.Direction == "bullish" {
			positive++
		} else if signal.Direction == "bearish" {
			negative++
		}
	}
	actionText := map[string]string{
		"BUY":  "技术面具备右侧关注条件",
		"SELL": "技术面转弱，优先控制回撤",
		"HOLD": "多空证据暂不充分，保持观察",
	}[action]
	return fmt.Sprintf("%s；当前趋势为%s，利多信号 %d 项、利空信号 %d 项，风险等级%s。", actionText, trend, positive, negative, risk)
}

func rsi(values []float64, period int) (float64, bool) {
	if len(values) <= period {
		return 0, false
	}
	var gain, loss float64
	for i := 1; i <= period; i++ {
		change := values[i] - values[i-1]
		if change >= 0 {
			gain += change
		} else {
			loss -= change
		}
	}
	avgGain := gain / float64(period)
	avgLoss := loss / float64(period)
	for i := period + 1; i < len(values); i++ {
		change := values[i] - values[i-1]
		gainValue, lossValue := 0.0, 0.0
		if change >= 0 {
			gainValue = change
		} else {
			lossValue = -change
		}
		avgGain = (avgGain*float64(period-1) + gainValue) / float64(period)
		avgLoss = (avgLoss*float64(period-1) + lossValue) / float64(period)
	}
	if avgLoss == 0 {
		if avgGain == 0 {
			return 50, true
		}
		return 100, true
	}
	rs := avgGain / avgLoss
	return 100 - 100/(1+rs), true
}

func ema(values []float64, period int) []float64 {
	if len(values) == 0 || period <= 0 {
		return nil
	}
	out := make([]float64, len(values))
	out[0] = values[0]
	alpha := 2.0 / float64(period+1)
	for i := 1; i < len(values); i++ {
		out[i] = values[i]*alpha + out[i-1]*(1-alpha)
	}
	return out
}

func macd(values []float64, fast, slow, signal int) (float64, float64, float64, bool) {
	if len(values) < slow+signal {
		return 0, 0, 0, false
	}
	fastEMA := ema(values, fast)
	slowEMA := ema(values, slow)
	dif := make([]float64, len(values))
	for i := range values {
		dif[i] = fastEMA[i] - slowEMA[i]
	}
	dea := ema(dif, signal)
	last := len(values) - 1
	hist := (dif[last] - dea[last]) * 2
	return dif[last], dea[last], hist, true
}

func kdjK(highs, lows, closes []float64, period int) (float64, bool) {
	if len(closes) < period {
		return 0, false
	}
	k := 50.0
	for i := period - 1; i < len(closes); i++ {
		high := maxOf(highs[i-period+1 : i+1])
		low := minOf(lows[i-period+1 : i+1])
		rsv := 50.0
		if high > low {
			rsv = (closes[i] - low) / (high - low) * 100
		}
		k = k*2/3 + rsv/3
	}
	return k, true
}

func atr(highs, lows, closes []float64, period int) (float64, bool) {
	if len(closes) <= period {
		return 0, false
	}
	trueRanges := make([]float64, 0, len(closes)-1)
	for i := 1; i < len(closes); i++ {
		range1 := highs[i] - lows[i]
		range2 := math.Abs(highs[i] - closes[i-1])
		range3 := math.Abs(lows[i] - closes[i-1])
		trueRanges = append(trueRanges, math.Max(range1, math.Max(range2, range3)))
	}
	if len(trueRanges) < period {
		return 0, false
	}
	return average(trueRanges[len(trueRanges)-period:]), true
}

func bollinger(values []float64, period int, deviations float64) (float64, float64, float64, bool) {
	if len(values) < period {
		return 0, 0, 0, false
	}
	window := values[len(values)-period:]
	middle := average(window)
	var variance float64
	for _, value := range window {
		diff := value - middle
		variance += diff * diff
	}
	stddev := math.Sqrt(variance / float64(period))
	return middle + deviations*stddev, middle, middle - deviations*stddev, true
}

func average(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	var sum float64
	for _, value := range values {
		sum += value
	}
	return sum / float64(len(values))
}

func maxOf(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	out := values[0]
	for _, value := range values[1:] {
		if value > out {
			out = value
		}
	}
	return out
}

func minOf(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	out := values[0]
	for _, value := range values[1:] {
		if value < out {
			out = value
		}
	}
	return out
}

func clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}

func floatPtr(value float64) *float64 {
	value = math.Round(value*100) / 100
	return &value
}

func sortedKeys(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
