package trading

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

type fakeQuotes struct {
	price float64
}

func (f fakeQuotes) Quote(context.Context, string) (domain.Quote, error) {
	price := f.price
	prev := price - 1
	return domain.Quote{Symbol: "600519", Name: "测试股票", Price: &price, PrevClose: &prev}, nil
}

type fakeAnalysis struct{}

func (fakeAnalysis) Analyze(context.Context, string) (domain.Analysis, error) {
	price := 100.0
	return domain.Analysis{
		Symbol:     "600519",
		Name:       "测试股票",
		Price:      &price,
		Score:      90,
		Action:     "BUY",
		Confidence: 0.85,
		Risk:       "中",
	}, nil
}

func newTradingStore(t *testing.T) *store.Store {
	t.Helper()
	state, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open() error = %v", err)
	}
	return state
}

func TestPaperBrokerBuyAndSell(t *testing.T) {
	state := newTradingStore(t)
	broker := NewPaperBroker(state, fakeQuotes{price: 100})
	order, err := broker.PlaceOrder(context.Background(), domain.OrderRequest{
		Symbol: "600519", Side: OrderBuy, OrderType: OrderMarket, Quantity: 100,
	}, "manual", "tester")
	if err != nil {
		t.Fatalf("buy PlaceOrder() error = %v", err)
	}
	if order.Status != OrderFilled || order.AvgFillPrice != 100 {
		t.Fatalf("buy order = %+v", order)
	}
	account, err := broker.Account(context.Background())
	if err != nil {
		t.Fatalf("Account() error = %v", err)
	}
	if len(account.Positions) != 1 || account.Positions[0].Quantity != 100 {
		t.Fatalf("positions = %+v", account.Positions)
	}
	if account.Cash >= 1_000_000 {
		t.Fatalf("cash was not reduced: %v", account.Cash)
	}

	sell, err := broker.PlaceOrder(context.Background(), domain.OrderRequest{
		Symbol: "600519", Side: OrderSell, OrderType: OrderMarket, Quantity: 100,
	}, "manual", "tester")
	if err != nil {
		t.Fatalf("sell PlaceOrder() error = %v", err)
	}
	if sell.Status != OrderFilled {
		t.Fatalf("sell order = %+v", sell)
	}
	account, err = broker.Account(context.Background())
	if err != nil {
		t.Fatalf("Account() after sell error = %v", err)
	}
	if len(account.Positions) != 0 {
		t.Fatalf("positions after sell = %+v", account.Positions)
	}
}

func TestPaperBrokerRequiresBoardLotForBuy(t *testing.T) {
	state := newTradingStore(t)
	broker := NewPaperBroker(state, fakeQuotes{price: 100})
	if _, err := broker.PlaceOrder(context.Background(), domain.OrderRequest{
		Symbol: "600519", Side: OrderBuy, OrderType: OrderMarket, Quantity: 10,
	}, "manual", "tester"); err == nil {
		t.Fatal("buy order accepted a non-board-lot quantity")
	}
}

func TestManagerCustodyPlacesOneOrderPerSymbolPerDay(t *testing.T) {
	state := newTradingStore(t)
	manager := NewManager(state, fakeAnalysis{}, fakeQuotes{price: 100}, ManagerConfig{Mode: "paper"}, nil)
	if _, err := manager.UpdateCustody(domain.CustodySettings{
		Enabled:         true,
		Symbols:         []string{"600519"},
		BuyScore:        80,
		SellScore:       30,
		MinConfidence:   0.70,
		MaxOrderValue:   20_000,
		IntervalSeconds: 300,
		AllowBuy:        true,
		AllowSell:       true,
	}, "ENABLE CUSTODY", "owner"); err != nil {
		t.Fatalf("UpdateCustody() error = %v", err)
	}
	orders, err := manager.RunCustodyOnce(context.Background(), "owner", true)
	if err != nil {
		t.Fatalf("RunCustodyOnce() error = %v", err)
	}
	if len(orders) != 1 {
		t.Fatalf("custody orders = %d, want 1", len(orders))
	}
	orders, err = manager.RunCustodyOnce(context.Background(), "owner", true)
	if err != nil {
		t.Fatalf("second RunCustodyOnce() error = %v", err)
	}
	if len(orders) != 0 {
		t.Fatalf("duplicate custody orders = %d, want 0", len(orders))
	}
}

func TestRemoteBrokerRequiresHTTPSUnlessExplicitlyAllowed(t *testing.T) {
	broker := NewRemoteBroker(RemoteConfig{
		BaseURL:   "http://192.168.1.20:9000",
		KeyID:     "key",
		Secret:    "secret",
		AccountID: "acct",
	})
	if broker.Configured() {
		t.Fatal("plain HTTP gateway configured without explicit opt-in")
	}
	broker = NewRemoteBroker(RemoteConfig{
		BaseURL:        "http://192.168.1.20:9000",
		KeyID:          "key",
		Secret:         "secret",
		AccountID:      "acct",
		AllowPlainHTTP: true,
	})
	if !broker.Configured() {
		t.Fatal("explicit internal HTTP gateway should be configurable")
	}
}

func TestLiveModeFallsBackWhenGatewayMissing(t *testing.T) {
	state := newTradingStore(t)
	manager := NewManager(state, fakeAnalysis{}, fakeQuotes{price: 100}, ManagerConfig{
		Mode:             "live",
		AllowLiveTrading: true,
	}, nil)
	if manager.Status().Mode != "paper" || manager.Status().LiveEnabled {
		t.Fatalf("status = %+v", manager.Status())
	}
}

func TestLiveCustodyRequiresExplicitServerPermission(t *testing.T) {
	state := newTradingStore(t)
	manager := NewManager(state, fakeAnalysis{}, fakeQuotes{price: 100}, ManagerConfig{
		Mode:             "live",
		AllowLiveTrading: true,
		AllowLiveCustody: false,
		Remote: RemoteConfig{
			BaseURL:   "https://broker.example",
			KeyID:     "key",
			Secret:    "secret",
			AccountID: "acct",
		},
	}, nil)
	if !manager.Status().LiveEnabled {
		t.Fatalf("live gateway should be enabled: %+v", manager.Status())
	}
	_, err := manager.UpdateCustody(domain.CustodySettings{
		Enabled:         true,
		Symbols:         []string{"600519"},
		BuyScore:        80,
		SellScore:       30,
		MinConfidence:   0.70,
		MaxOrderValue:   20_000,
		IntervalSeconds: 300,
		AllowBuy:        true,
		AllowSell:       true,
	}, "ENABLE CUSTODY", "owner")
	if err == nil {
		t.Fatal("live custody was enabled without ALLOW_LIVE_CUSTODY")
	}
}
