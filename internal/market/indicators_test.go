package market

import (
	"math"
	"testing"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

func TestRSIHandlesFlatAndDirectionalSeries(t *testing.T) {
	flat := make([]float64, 30)
	for i := range flat {
		flat[i] = 10
	}
	if got, ok := rsi(flat, 14); !ok || got != 50 {
		t.Fatalf("flat RSI = %v, %v; want 50, true", got, ok)
	}

	rising := make([]float64, 30)
	for i := range rising {
		rising[i] = float64(i + 1)
	}
	if got, ok := rsi(rising, 14); !ok || got < 99 {
		t.Fatalf("rising RSI = %v, %v; want near 100", got, ok)
	}
}

func TestAnalyzeBarsProducesCompleteTechnicalView(t *testing.T) {
	bars := make([]domain.Bar, 120)
	for i := range bars {
		price := 10 + float64(i)*0.05
		bars[i] = domain.Bar{
			Date:   "2026-01-01",
			Open:   price - 0.03,
			Close:  price,
			High:   price + 0.08,
			Low:    price - 0.08,
			Volume: 100000 + float64(i*1000),
		}
	}
	result := analyzeBars(bars, map[string]bool{
		"ma_cross":         true,
		"macd_reversal":    true,
		"rsi_reversal":     true,
		"volume_breakout":  true,
		"channel_breakout": true,
	})
	if !result.Complete {
		t.Fatal("Complete = false, want true for 120 bars")
	}
	if result.Indicators.MA60 == nil || result.Indicators.RSI14 == nil || result.Indicators.ATR14 == nil {
		t.Fatalf("missing indicators: %+v", result.Indicators)
	}
	if result.Score < 0 || result.Score > 100 {
		t.Fatalf("score = %d, want 0..100", result.Score)
	}
	if result.Action != "BUY" && result.Action != "HOLD" && result.Action != "SELL" {
		t.Fatalf("unexpected action %q", result.Action)
	}
	if result.Confidence < 0 || result.Confidence > 0.92 {
		t.Fatalf("confidence = %v", result.Confidence)
	}
	if len(result.Signals) == 0 {
		t.Fatal("expected at least one explainable signal")
	}
}

func TestIndicatorsReturnUnavailableWhenSampleIsShort(t *testing.T) {
	result := analyzeBars([]domain.Bar{{Close: 10}, {Close: 11}}, nil)
	if result.Action != "HOLD" || result.Risk != "未知" {
		t.Fatalf("short sample result = %+v", result)
	}
	if result.Indicators.RSI14 != nil {
		t.Fatal("RSI should be nil when data is insufficient")
	}
}

func TestBollingerUsesPopulationDeviation(t *testing.T) {
	values := []float64{1, 2, 3, 4, 5}
	upper, middle, lower, ok := bollinger(values, 5, 2)
	if !ok {
		t.Fatal("bollinger returned false")
	}
	if middle != 3 {
		t.Fatalf("middle = %v, want 3", middle)
	}
	if math.Abs((upper-lower)-4*math.Sqrt(2)) > 1e-9 {
		t.Fatalf("band width = %v", upper-lower)
	}
}
