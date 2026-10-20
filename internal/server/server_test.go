package server

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/config"
	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/market"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

type serverStubProvider struct{}

func (serverStubProvider) Name() string { return "test-live" }

func (serverStubProvider) Quotes(_ context.Context, symbols []string) ([]domain.Quote, error) {
	out := make([]domain.Quote, 0, len(symbols))
	for _, symbol := range symbols {
		price := 100.0
		change := 1.2
		out = append(out, domain.Quote{Symbol: symbol, Name: "测试股票", Price: &price, ChangePct: &change})
	}
	return out, nil
}

func (serverStubProvider) Indices(context.Context) ([]domain.IndexQuote, error) {
	price := 3200.0
	change := 0.6
	return []domain.IndexQuote{{Code: "000001", Name: "上证指数", Price: &price, ChangePct: &change}}, nil
}

func (serverStubProvider) Kline(_ context.Context, _ string, limit int) ([]domain.Bar, error) {
	if limit > 140 {
		limit = 140
	}
	bars := make([]domain.Bar, limit)
	for i := range bars {
		price := 50 + float64(i)*0.2
		bars[i] = domain.Bar{Date: "2026-10-01", Open: price, Close: price, High: price + 1, Low: price - 1, Volume: 100000}
	}
	return bars, nil
}

func testConfig() config.Config {
	return config.Config{
		Address:  ":0",
		DataFile: "state.json",
		Version:  "test",
		Timeout:  5 * time.Second,
	}
}

func newTestServer(t *testing.T, cfg config.Config) *httptest.Server {
	t.Helper()
	state, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open() error = %v", err)
	}
	service := market.NewService(serverStubProvider{}, state)
	app, err := New(cfg, state, service, nil)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	return httptest.NewServer(app)
}

func requestJSON(t *testing.T, client *http.Client, method, url string, body any) (int, map[string]any) {
	t.Helper()
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body: %v", err)
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, url, reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("request %s %s: %v", method, url, err)
	}
	defer resp.Body.Close()
	var payload map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp.StatusCode, payload
}

func TestDashboardAndStockMutations(t *testing.T) {
	server := newTestServer(t, testConfig())
	defer server.Close()
	client := server.Client()

	status, payload := requestJSON(t, client, http.MethodGet, server.URL+"/api/v1/dashboard", nil)
	if status != http.StatusOK {
		t.Fatalf("dashboard status = %d, payload = %v", status, payload)
	}
	stocks, ok := payload["stocks"].([]any)
	if !ok || len(stocks) != 9 {
		t.Fatalf("dashboard stocks = %#v", payload["stocks"])
	}
	first := stocks[0].(map[string]any)
	if first["symbol"] != "600519" || first["name"] != "贵州茅台" {
		t.Fatalf("stock identity = %#v", first)
	}

	status, payload = requestJSON(t, client, http.MethodPost, server.URL+"/api/v1/stocks", map[string]any{
		"symbol": "600000",
		"name":   "浦发银行",
		"notes":  "测试",
	})
	if status != http.StatusCreated {
		t.Fatalf("add stock status = %d, payload = %v", status, payload)
	}

	status, payload = requestJSON(t, client, http.MethodDelete, server.URL+"/api/v1/stocks/600000", nil)
	if status != http.StatusOK || payload["removed"] != true {
		t.Fatalf("delete stock status = %d, payload = %v", status, payload)
	}
}

func TestAnalyzeAndRiskSettings(t *testing.T) {
	server := newTestServer(t, testConfig())
	defer server.Close()
	client := server.Client()

	status, payload := requestJSON(t, client, http.MethodPost, server.URL+"/api/v1/analyze", map[string]any{"symbol": "600519"})
	if status != http.StatusOK {
		t.Fatalf("analyze status = %d, payload = %v", status, payload)
	}
	if payload["symbol"] != "600519" || payload["action"] == "" {
		t.Fatalf("analysis payload = %#v", payload)
	}

	status, payload = requestJSON(t, client, http.MethodPut, server.URL+"/api/v1/settings", map[string]any{
		"max_position_pct": 20,
		"stop_loss_pct":    6,
		"daily_loss_pct":   2,
		"min_confidence":   0.7,
	})
	if status != http.StatusOK || payload["max_position_pct"].(float64) != 20 {
		t.Fatalf("settings status = %d, payload = %v", status, payload)
	}
}

func TestLoginProtectsAPI(t *testing.T) {
	cfg := testConfig()
	cfg.APIToken = "secret-token"
	server := newTestServer(t, cfg)
	defer server.Close()

	status, _ := requestJSON(t, server.Client(), http.MethodGet, server.URL+"/api/v1/dashboard", nil)
	if status != http.StatusUnauthorized {
		t.Fatalf("unauthenticated dashboard status = %d, want 401", status)
	}

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatalf("cookie jar: %v", err)
	}
	client := &http.Client{Jar: jar}
	status, payload := requestJSON(t, client, http.MethodPost, server.URL+"/login", map[string]any{"token": "secret-token"})
	if status != http.StatusOK || payload["ok"] != true {
		t.Fatalf("login status = %d, payload = %v", status, payload)
	}
	status, _ = requestJSON(t, client, http.MethodGet, server.URL+"/api/v1/dashboard", nil)
	if status != http.StatusOK {
		t.Fatalf("authenticated dashboard status = %d, want 200", status)
	}
}

func TestWebAssetsAndHealth(t *testing.T) {
	server := newTestServer(t, testConfig())
	defer server.Close()

	resp, err := server.Client().Get(server.URL + "/")
	if err != nil {
		t.Fatalf("GET /: %v", err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK || !strings.Contains(string(raw), "量化控制中心") {
		t.Fatalf("index status = %d, body = %s", resp.StatusCode, raw)
	}

	status, payload := requestJSON(t, server.Client(), http.MethodGet, server.URL+"/health", nil)
	if status != http.StatusOK || payload["status"] != "ok" {
		t.Fatalf("health status = %d, payload = %v", status, payload)
	}

	resp, err = server.Client().Get(server.URL + "/assets/app.css")
	if err != nil {
		t.Fatalf("GET css: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("css status = %d", resp.StatusCode)
	}
}
