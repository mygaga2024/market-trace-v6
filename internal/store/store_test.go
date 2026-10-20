package store

import (
	"errors"
	"path/filepath"
	"testing"
)

func TestStoreLifecycleAndPersistence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	state, err := Open(path)
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	if got := len(state.Watchlist()); got != 9 {
		t.Fatalf("seed watchlist length = %d, want 9", got)
	}

	item, err := state.AddStock("600000", "浦发银行", "测试")
	if err != nil {
		t.Fatalf("AddStock() error = %v", err)
	}
	if item.Symbol != "600000" {
		t.Fatalf("AddStock() symbol = %q", item.Symbol)
	}
	if _, err := state.AddStock("600000", "浦发银行", ""); !errors.Is(err, ErrExists) {
		t.Fatalf("duplicate AddStock() error = %v, want ErrExists", err)
	}
	if _, err := state.AddStock("abc", "无效", ""); err == nil {
		t.Fatal("AddStock() accepted invalid symbol")
	}

	if err := state.ToggleStrategy("rsi_reversal", false); err != nil {
		t.Fatalf("ToggleStrategy() error = %v", err)
	}
	if _, err := state.UpdateSettings(state.Settings()); err != nil {
		t.Fatalf("UpdateSettings() error = %v", err)
	}
	if err := state.RemoveStock("600000"); err != nil {
		t.Fatalf("RemoveStock() error = %v", err)
	}
	if err := state.RemoveStock("600000"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("second RemoveStock() error = %v, want ErrNotFound", err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatalf("reopen state: %v", err)
	}
	if reopened.HasStock("600000") {
		t.Fatal("removed stock persisted")
	}
	for _, strategy := range reopened.Strategies() {
		if strategy.Key == "rsi_reversal" && strategy.Enabled {
			t.Fatal("disabled strategy persisted as enabled")
		}
	}
	if len(reopened.Audits(100)) < 4 {
		t.Fatalf("audit count = %d, want at least 4", len(reopened.Audits(100)))
	}
}

func TestStoreRejectsUnsafeRiskSettings(t *testing.T) {
	state, err := Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	settings := state.Settings()
	settings.MaxPositionPct = 0
	if _, err := state.UpdateSettings(settings); err == nil {
		t.Fatal("UpdateSettings() accepted zero position limit")
	}
}
