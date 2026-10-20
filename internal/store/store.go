package store

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

const stateVersion = 1

var (
	ErrNotFound = errors.New("not found")
	ErrExists   = errors.New("already exists")
)

type State struct {
	Version    int                 `json:"version"`
	Watchlist  []domain.WatchItem  `json:"watchlist"`
	Decisions  []domain.Decision   `json:"decisions"`
	Audits     []domain.AuditEvent `json:"audits"`
	Settings   domain.RiskSettings `json:"settings"`
	Strategies map[string]bool     `json:"strategies"`
	UpdatedAt  time.Time           `json:"updated_at"`
}

type Store struct {
	mu    sync.RWMutex
	path  string
	state State
}

func Open(path string) (*Store, error) {
	s := &Store{path: path}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, fmt.Errorf("create data directory: %w", err)
	}

	raw, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(raw, &s.state); err != nil {
			return nil, fmt.Errorf("decode state: %w", err)
		}
		s.normalize()
		return s, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("read state: %w", err)
	}

	s.state = seedState()
	if err := s.persistLocked(); err != nil {
		return nil, err
	}
	return s, nil
}

func seedState() State {
	now := time.Now()
	seeds := []struct {
		symbol string
		name   string
		notes  string
	}{
		{"600519", "贵州茅台", "核心消费"},
		{"300750", "宁德时代", "新能源"},
		{"000858", "五粮液", "核心消费"},
		{"601318", "中国平安", "金融"},
		{"002594", "比亚迪", "汽车"},
		{"600036", "招商银行", "金融"},
		{"000001", "平安银行", "金融"},
		{"688981", "中芯国际", "半导体"},
		{"600900", "长江电力", "红利"},
	}
	watchlist := make([]domain.WatchItem, 0, len(seeds))
	for i, item := range seeds {
		watchlist = append(watchlist, domain.WatchItem{
			Symbol:  item.symbol,
			Name:    item.name,
			Notes:   item.notes,
			AddedAt: now.Add(-time.Duration(len(seeds)-i) * time.Hour),
		})
	}

	return State{
		Version:   stateVersion,
		Watchlist: watchlist,
		Settings: domain.RiskSettings{
			MaxPositionPct: 25,
			StopLossPct:    8,
			DailyLossPct:   3,
			MinConfidence:  0.62,
		},
		Strategies: map[string]bool{
			"ma_cross":         true,
			"macd_reversal":    true,
			"rsi_reversal":     true,
			"volume_breakout":  true,
			"channel_breakout": true,
		},
		Audits: []domain.AuditEvent{
			newAudit("system", "初始化", "system", "Market Trace Go", "完成种子自选股与风控配置初始化", now.Add(-3*time.Minute)),
		},
		UpdatedAt: now,
	}
}

func (s *Store) normalize() {
	if s.state.Version == 0 {
		s.state.Version = stateVersion
	}
	if s.state.Settings.MaxPositionPct == 0 {
		s.state.Settings = domain.RiskSettings{
			MaxPositionPct: 25,
			StopLossPct:    8,
			DailyLossPct:   3,
			MinConfidence:  0.62,
		}
	}
	if s.state.Strategies == nil {
		s.state.Strategies = map[string]bool{
			"ma_cross":         true,
			"macd_reversal":    true,
			"rsi_reversal":     true,
			"volume_breakout":  true,
			"channel_breakout": true,
		}
	}
	if s.state.Watchlist == nil {
		s.state.Watchlist = []domain.WatchItem{}
	}
	if s.state.Decisions == nil {
		s.state.Decisions = []domain.Decision{}
	}
	if s.state.Audits == nil {
		s.state.Audits = []domain.AuditEvent{}
	}
}

func (s *Store) persistLocked() error {
	s.state.Version = stateVersion
	s.state.UpdatedAt = time.Now()
	raw, err := json.MarshalIndent(s.state, "", "  ")
	if err != nil {
		return fmt.Errorf("encode state: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(s.path), ".market-trace-*.json")
	if err != nil {
		return fmt.Errorf("create temporary state: %w", err)
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return fmt.Errorf("set state permissions: %w", err)
	}
	if _, err := tmp.Write(raw); err != nil {
		tmp.Close()
		return fmt.Errorf("write state: %w", err)
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return fmt.Errorf("sync state: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("close state: %w", err)
	}
	if err := os.Rename(tmpName, s.path); err != nil {
		return fmt.Errorf("replace state: %w", err)
	}
	return nil
}

func (s *Store) Watchlist() []domain.WatchItem {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]domain.WatchItem, len(s.state.Watchlist))
	copy(out, s.state.Watchlist)
	return out
}

func (s *Store) HasStock(symbol string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, item := range s.state.Watchlist {
		if item.Symbol == symbol {
			return true
		}
	}
	return false
}

func (s *Store) AddStock(symbol, name, notes string) (domain.WatchItem, error) {
	symbol = strings.TrimSpace(symbol)
	name = strings.TrimSpace(name)
	notes = strings.TrimSpace(notes)
	if !validSymbol(symbol) {
		return domain.WatchItem{}, fmt.Errorf("股票代码需为 6 位数字")
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	for _, item := range s.state.Watchlist {
		if item.Symbol == symbol {
			return domain.WatchItem{}, ErrExists
		}
	}
	item := domain.WatchItem{
		Symbol:  symbol,
		Name:    name,
		Notes:   notes,
		AddedAt: time.Now(),
	}
	s.state.Watchlist = append([]domain.WatchItem{item}, s.state.Watchlist...)
	s.state.Audits = prependAudit(s.state.Audits, newAudit("stock", "添加自选", "operator", symbol, fmt.Sprintf("添加 %s %s", symbol, name), time.Now()))
	if err := s.persistLocked(); err != nil {
		return domain.WatchItem{}, err
	}
	return item, nil
}

func (s *Store) RemoveStock(symbol string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, item := range s.state.Watchlist {
		if item.Symbol != symbol {
			continue
		}
		s.state.Watchlist = append(s.state.Watchlist[:i], s.state.Watchlist[i+1:]...)
		s.state.Audits = prependAudit(s.state.Audits, newAudit("stock", "移除自选", "operator", symbol, "从自选名单移除 "+item.Name, time.Now()))
		return s.persistLocked()
	}
	return ErrNotFound
}

func (s *Store) RecordAnalysis(a domain.Analysis) error {
	decision := domain.Decision{
		ID:         newID("dec"),
		Symbol:     a.Symbol,
		Name:       a.Name,
		Action:     a.Action,
		Score:      a.Score,
		Confidence: a.Confidence,
		Risk:       a.Risk,
		Summary:    a.Summary,
		CreatedAt:  a.GeneratedAt,
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	s.state.Decisions = append([]domain.Decision{decision}, s.state.Decisions...)
	if len(s.state.Decisions) > 500 {
		s.state.Decisions = s.state.Decisions[:500]
	}
	s.state.Audits = prependAudit(s.state.Audits, newAudit(
		"analysis",
		"生成决策",
		"go-engine",
		a.Symbol,
		fmt.Sprintf("%s %s，评分 %d，置信度 %.0f%%", a.Name, a.Action, a.Score, a.Confidence*100),
		time.Now(),
	))
	return s.persistLocked()
}

func (s *Store) Decisions() []domain.Decision {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]domain.Decision, len(s.state.Decisions))
	copy(out, s.state.Decisions)
	return out
}

func (s *Store) LatestDecision(symbol string) (domain.Decision, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, decision := range s.state.Decisions {
		if decision.Symbol == symbol {
			return decision, true
		}
	}
	return domain.Decision{}, false
}

func (s *Store) Audits(limit int) []domain.AuditEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if limit <= 0 || limit > len(s.state.Audits) {
		limit = len(s.state.Audits)
	}
	out := make([]domain.AuditEvent, limit)
	copy(out, s.state.Audits[:limit])
	return out
}

func (s *Store) Settings() domain.RiskSettings {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.state.Settings
}

func (s *Store) UpdateSettings(settings domain.RiskSettings) (domain.RiskSettings, error) {
	if settings.MaxPositionPct <= 0 || settings.MaxPositionPct > 100 {
		return domain.RiskSettings{}, fmt.Errorf("单票仓位上限需在 0-100 之间")
	}
	if settings.StopLossPct <= 0 || settings.StopLossPct > 50 {
		return domain.RiskSettings{}, fmt.Errorf("止损比例需在 0-50 之间")
	}
	if settings.DailyLossPct <= 0 || settings.DailyLossPct > 30 {
		return domain.RiskSettings{}, fmt.Errorf("单日亏损阈值需在 0-30 之间")
	}
	if settings.MinConfidence < 0 || settings.MinConfidence > 1 {
		return domain.RiskSettings{}, fmt.Errorf("最低置信度需在 0-1 之间")
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	s.state.Settings = settings
	s.state.Audits = prependAudit(s.state.Audits, newAudit(
		"risk",
		"更新风控",
		"operator",
		"risk-settings",
		fmt.Sprintf("单票 %.0f%%，止损 %.0f%%，日亏 %.0f%%，置信度 %.0f%%",
			settings.MaxPositionPct, settings.StopLossPct, settings.DailyLossPct, settings.MinConfidence*100),
		time.Now(),
	))
	if err := s.persistLocked(); err != nil {
		return domain.RiskSettings{}, err
	}
	return settings, nil
}

func (s *Store) Strategies() []domain.StrategyToggle {
	s.mu.RLock()
	defer s.mu.RUnlock()
	defs := []struct {
		key  string
		name string
		desc string
	}{
		{"ma_cross", "均线交叉", "MA5 / MA20 多空交叉与趋势确认"},
		{"macd_reversal", "MACD 反转", "柱体由负转正，捕捉动能修复"},
		{"rsi_reversal", "RSI 反转", "超卖反弹与超买降温信号"},
		{"volume_breakout", "量价突破", "价格突破近期高点并由成交量确认"},
		{"channel_breakout", "通道突破", "布林带与支撑阻力区间突破"},
	}
	out := make([]domain.StrategyToggle, 0, len(defs))
	for _, def := range defs {
		out = append(out, domain.StrategyToggle{
			Key:         def.key,
			Name:        def.name,
			Description: def.desc,
			Enabled:     s.state.Strategies[def.key],
		})
	}
	return out
}

func (s *Store) EnabledStrategies() map[string]bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]bool, len(s.state.Strategies))
	for key, enabled := range s.state.Strategies {
		out[key] = enabled
	}
	return out
}

func (s *Store) ToggleStrategy(key string, enabled bool) error {
	known := map[string]string{
		"ma_cross":         "均线交叉",
		"macd_reversal":    "MACD 反转",
		"rsi_reversal":     "RSI 反转",
		"volume_breakout":  "量价突破",
		"channel_breakout": "通道突破",
	}
	name, ok := known[key]
	if !ok {
		return ErrNotFound
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	s.state.Strategies[key] = enabled
	status := "停用"
	if enabled {
		status = "启用"
	}
	s.state.Audits = prependAudit(s.state.Audits, newAudit("strategy", "切换策略", "operator", key, status+" "+name, time.Now()))
	return s.persistLocked()
}

func (s *Store) SeedAudit(category, action, target, detail string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.state.Audits = prependAudit(s.state.Audits, newAudit(category, action, "system", target, detail, time.Now()))
	_ = s.persistLocked()
}

func prependAudit(items []domain.AuditEvent, item domain.AuditEvent) []domain.AuditEvent {
	items = append([]domain.AuditEvent{item}, items...)
	if len(items) > 1000 {
		items = items[:1000]
	}
	return items
}

func newAudit(category, action, actor, target, detail string, at time.Time) domain.AuditEvent {
	return domain.AuditEvent{
		ID:        newID("aud"),
		Category:  category,
		Action:    action,
		Actor:     actor,
		Target:    target,
		Detail:    detail,
		CreatedAt: at,
	}
}

func newID(prefix string) string {
	raw := make([]byte, 6)
	if _, err := rand.Read(raw); err != nil {
		return fmt.Sprintf("%s-%d", prefix, time.Now().UnixNano())
	}
	return prefix + "-" + hex.EncodeToString(raw)
}

func validSymbol(symbol string) bool {
	if len(symbol) != 6 {
		return false
	}
	for _, r := range symbol {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
