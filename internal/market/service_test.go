package market

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

type stubProvider struct {
	quoteErr error
}

func (s *stubProvider) Name() string {
	return "stub-live"
}

func (s *stubProvider) Quotes(_ context.Context, symbols []string) ([]domain.Quote, error) {
	if s.quoteErr != nil {
		return nil, s.quoteErr
	}
	price := 1888.0
	changePct := 1.25
	out := make([]domain.Quote, 0, len(symbols))
	for _, symbol := range symbols {
		value := price
		change := changePct
		out = append(out, domain.Quote{
			Symbol:    symbol,
			Name:      "测试股票",
			Price:     &value,
			ChangePct: &change,
			UpdatedAt: time.Now(),
		})
	}
	return out, nil
}

func (s *stubProvider) Indices(context.Context) ([]domain.IndexQuote, error) {
	price := 3500.0
	change := 0.4
	return []domain.IndexQuote{{Code: "000001", Name: "上证指数", Price: &price, ChangePct: &change}}, nil
}

func (s *stubProvider) Kline(_ context.Context, _ string, limit int) ([]domain.Bar, error) {
	if limit > 140 {
		limit = 140
	}
	bars := make([]domain.Bar, limit)
	for i := range bars {
		price := 1500 + float64(i)*2
		bars[i] = domain.Bar{
			Date:   "2026-10-01",
			Open:   price - 1,
			Close:  price,
			High:   price + 3,
			Low:    price - 3,
			Volume: 100000 + float64(i*200),
		}
	}
	return bars, nil
}

func newTestService(t *testing.T, provider Provider) (*Service, *store.Store) {
	t.Helper()
	state, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open() error = %v", err)
	}
	return NewService(provider, state), state
}

func TestDashboardPreservesStockIdentity(t *testing.T) {
	service, _ := newTestService(t, &stubProvider{})
	dashboard := service.Dashboard(context.Background())
	if len(dashboard.Stocks) != 9 {
		t.Fatalf("stocks = %d, want 9", len(dashboard.Stocks))
	}
	first := dashboard.Stocks[0]
	if first.Symbol != "600519" || first.Name != "贵州茅台" {
		t.Fatalf("first stock identity = %q / %q", first.Symbol, first.Name)
	}
	if first.Price == nil || *first.Price != 1888 {
		t.Fatalf("first stock price = %v", first.Price)
	}
	if !dashboard.Overview.LiveMarket {
		t.Fatal("LiveMarket = false")
	}
	if dashboard.Risk.RAI == nil {
		t.Fatal("RAI should be available")
	}
}

func TestDashboardFetchesNewStockDespiteWarmQuoteCache(t *testing.T) {
	service, state := newTestService(t, &stubProvider{})
	service.Dashboard(context.Background())
	if _, err := state.AddStock("600000", "浦发银行", "测试"); err != nil {
		t.Fatalf("AddStock() error = %v", err)
	}

	dashboard := service.Dashboard(context.Background())
	for _, stock := range dashboard.Stocks {
		if stock.Symbol == "600000" {
			if stock.Price == nil || *stock.Price != 1888 {
				t.Fatalf("new stock price = %v, want a fresh quote", stock.Price)
			}
			return
		}
	}
	t.Fatal("new stock missing from dashboard")
}

func TestAnalyzeRecordsDecision(t *testing.T) {
	service, state := newTestService(t, &stubProvider{})
	analysis, err := service.Analyze(context.Background(), "600519")
	if err != nil {
		t.Fatalf("Analyze() error = %v", err)
	}
	if analysis.Symbol != "600519" || analysis.Name != "测试股票" {
		t.Fatalf("analysis identity = %+v", analysis)
	}
	if analysis.Price == nil || *analysis.Price != 1888 {
		t.Fatalf("analysis price = %v", analysis.Price)
	}
	if len(analysis.Bars) > 80 {
		t.Fatalf("chart bars = %d, want <= 80", len(analysis.Bars))
	}
	decisions := state.Decisions()
	if len(decisions) != 1 {
		t.Fatalf("decisions = %d, want 1", len(decisions))
	}
	if decisions[0].Action != analysis.Action {
		t.Fatalf("recorded action = %q, want %q", decisions[0].Action, analysis.Action)
	}
}

func TestDashboardDegradesExplicitlyWhenProviderFails(t *testing.T) {
	service, _ := newTestService(t, &stubProvider{quoteErr: errors.New("offline")})
	dashboard := service.Dashboard(context.Background())
	if dashboard.Overview.LiveMarket {
		t.Fatal("LiveMarket = true while provider is offline")
	}
	if dashboard.Overview.DataSource != "unavailable" {
		t.Fatalf("data source = %q, want unavailable", dashboard.Overview.DataSource)
	}
	if dashboard.Stocks[0].Price != nil {
		t.Fatal("fallback must not invent a price")
	}
	if dashboard.Agents[0].Status != "degraded" {
		t.Fatalf("market agent status = %q", dashboard.Agents[0].Status)
	}
}
