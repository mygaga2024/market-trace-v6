package trading

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/id"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

type AnalysisSource interface {
	Analyze(ctx context.Context, symbol string) (domain.Analysis, error)
}

type ManagerConfig struct {
	Mode             string
	AllowLiveTrading bool
	AllowLiveCustody bool
	Remote           RemoteConfig
}

func ManagerConfigFromEnv() ManagerConfig {
	mode := strings.ToLower(strings.TrimSpace(os.Getenv("TRADING_MODE")))
	if mode == "" {
		mode = "paper"
	}
	return ManagerConfig{
		Mode:             mode,
		AllowLiveTrading: envBool("ALLOW_LIVE_TRADING"),
		AllowLiveCustody: envBool("ALLOW_LIVE_CUSTODY"),
		Remote:           RemoteConfigFromEnv(),
	}
}

type Manager struct {
	store    *store.Store
	analysis AnalysisSource
	quotes   PriceSource
	paper    *PaperBroker
	remote   *RemoteBroker
	broker   Broker
	status   domain.TradingStatus
	logger   *slog.Logger

	custodyMu sync.Mutex
	now       func() time.Time
	location  *time.Location
}

func NewManager(state *store.Store, analysis AnalysisSource, quotes PriceSource, cfg ManagerConfig, logger *slog.Logger) *Manager {
	if logger == nil {
		logger = slog.Default()
	}
	paper := NewPaperBroker(state, quotes)
	remote := NewRemoteBroker(cfg.Remote)
	status := domain.TradingStatus{
		Mode:               "paper",
		Broker:             paper.Name(),
		GatewayConfigured:  remote.Configured(),
		CustodyLiveAllowed: cfg.AllowLiveCustody,
		Message:            "当前为内置模拟盘，不会向券商发送真实委托。",
	}
	var broker Broker = paper
	if cfg.Mode == "live" {
		switch {
		case !cfg.AllowLiveTrading:
			status.Message = "TRADING_MODE=live 已请求，但 ALLOW_LIVE_TRADING 未开启；已安全降级为模拟盘。"
		case !remote.Configured():
			status.Message = "实盘所需官方券商网关未配置：" + remote.ConfigError() + "；已安全降级为模拟盘。"
		default:
			broker = remote
			status.Mode = "live"
			status.Broker = remote.Name()
			status.LiveEnabled = true
			status.Message = "已连接官方券商网关；所有实盘委托都会写入审计记录。"
		}
	}
	location, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		location = time.FixedZone("CST", 8*3600)
	}
	return &Manager{
		store:    state,
		analysis: analysis,
		quotes:   quotes,
		paper:    paper,
		remote:   remote,
		broker:   broker,
		status:   status,
		logger:   logger,
		now:      time.Now,
		location: location,
	}
}

func (m *Manager) Status() domain.TradingStatus {
	return m.status
}

func (m *Manager) Account(ctx context.Context) domain.Account {
	account, err := m.broker.Account(ctx)
	if err != nil {
		return domain.Account{
			Mode:      m.status.Mode,
			Broker:    m.status.Broker,
			Positions: []domain.Position{},
			UpdatedAt: time.Now(),
			Degraded:  true,
			Message:   err.Error(),
		}
	}
	return account
}

func (m *Manager) Orders(ctx context.Context, limit int) ([]domain.Order, error) {
	return m.broker.Orders(ctx, limit)
}

func (m *Manager) PlaceOrder(ctx context.Context, request domain.OrderRequest, source, actor string) (domain.Order, error) {
	order, err := m.broker.PlaceOrder(ctx, request, source, actor)
	if err != nil {
		m.store.RecordAudit("trading", "委托失败", actor, request.Symbol, err.Error())
		return domain.Order{}, err
	}
	if m.status.LiveEnabled {
		m.store.RecordAudit(
			"trading",
			"提交实盘委托",
			actor,
			order.ID,
			fmt.Sprintf("%s %s %d 股，券商状态 %s", order.Symbol, order.Side, order.Quantity, order.Status),
		)
	}
	return order, nil
}

func (m *Manager) CancelOrder(ctx context.Context, orderID, actor string) (domain.Order, error) {
	order, err := m.broker.CancelOrder(ctx, orderID, actor)
	if err != nil {
		return domain.Order{}, err
	}
	if m.status.LiveEnabled {
		m.store.RecordAudit("trading", "撤销实盘委托", actor, order.ID, "券商已接收撤单请求")
	}
	return order, nil
}

func (m *Manager) CustodySettings() domain.CustodySettings {
	return m.store.TradingSnapshot().Custody
}

func (m *Manager) UpdateCustody(settings domain.CustodySettings, confirmation, actor string) (domain.CustodySettings, error) {
	current := m.CustodySettings()
	settings.Symbols = normalizeSymbols(settings.Symbols)
	if len(settings.Symbols) == 0 {
		return domain.CustodySettings{}, errors.New("托管交易至少需要一只股票")
	}
	if len(settings.Symbols) > 20 {
		return domain.CustodySettings{}, errors.New("托管股票最多 20 只")
	}
	if settings.BuyScore < 50 || settings.BuyScore > 100 {
		return domain.CustodySettings{}, errors.New("买入评分阈值需在 50-100 之间")
	}
	if settings.SellScore < 0 || settings.SellScore > 50 || settings.SellScore >= settings.BuyScore {
		return domain.CustodySettings{}, errors.New("卖出评分阈值需在 0-50 之间且低于买入阈值")
	}
	if settings.MinConfidence < 0.5 || settings.MinConfidence > 0.95 {
		return domain.CustodySettings{}, errors.New("最低置信度需在 50%-95% 之间")
	}
	if settings.MaxOrderValue < 100 || settings.MaxOrderValue > 10_000_000 {
		return domain.CustodySettings{}, errors.New("单次委托上限需在 100-10000000 元之间")
	}
	if settings.IntervalSeconds < 60 || settings.IntervalSeconds > 86400 {
		return domain.CustodySettings{}, errors.New("托管检查间隔需在 60-86400 秒之间")
	}
	if !settings.AllowBuy && !settings.AllowSell {
		return domain.CustodySettings{}, errors.New("买入和卖出至少开启一项")
	}
	if settings.Enabled && !current.Enabled && confirmation != "ENABLE CUSTODY" {
		return domain.CustodySettings{}, errors.New("开启托管需要明确确认")
	}
	if settings.Enabled && m.status.LiveEnabled && !m.status.CustodyLiveAllowed {
		return domain.CustodySettings{}, errors.New("实盘托管未授权：需服务端设置 ALLOW_LIVE_CUSTODY=true")
	}
	settings.LastRunAt = current.LastRunAt
	settings.LastResult = current.LastResult
	err := m.store.UpdateTrading(func(state *store.TradingState) error {
		state.Custody = settings
		return nil
	})
	if err != nil {
		return domain.CustodySettings{}, err
	}
	action := "更新托管参数"
	if settings.Enabled != current.Enabled {
		if settings.Enabled {
			action = "开启托管交易"
		} else {
			action = "停止托管交易"
		}
	}
	m.store.RecordAudit("custody", action, actor, "custody-settings", strings.Join(settings.Symbols, ","))
	return settings, nil
}

func (m *Manager) RunCustodyOnce(ctx context.Context, actor string, force bool) ([]domain.Order, error) {
	m.custodyMu.Lock()
	defer m.custodyMu.Unlock()

	settings := m.CustodySettings()
	if !settings.Enabled {
		return nil, errors.New("托管交易未开启")
	}
	if m.status.LiveEnabled && !m.status.CustodyLiveAllowed {
		return nil, errors.New("实盘托管未授权")
	}
	now := m.now().In(m.location)
	if m.status.LiveEnabled && !marketOpen(now) {
		return nil, errors.New("实盘托管只允许在 A 股连续竞价时段执行")
	}
	if !force && !marketOpen(now) {
		return nil, errors.New("当前不在 A 股连续竞价时段")
	}

	orders, err := m.broker.Orders(ctx, 200)
	if err != nil {
		m.recordCustodyResult(now, "读取委托失败: "+err.Error())
		return nil, err
	}
	account, err := m.broker.Account(ctx)
	if err != nil {
		m.recordCustodyResult(now, "读取账户失败: "+err.Error())
		return nil, err
	}
	positionBySymbol := make(map[string]domain.Position, len(account.Positions))
	for _, position := range account.Positions {
		positionBySymbol[position.Symbol] = position
	}

	placed := make([]domain.Order, 0)
	failures := make([]string, 0)
	for _, symbol := range settings.Symbols {
		analysis, analysisErr := m.analysis.Analyze(ctx, symbol)
		if analysisErr != nil {
			failures = append(failures, symbol+" 分析失败")
			continue
		}
		if analysis.Confidence < settings.MinConfidence {
			continue
		}
		side := ""
		if settings.AllowBuy && analysis.Score >= settings.BuyScore && analysis.Action == "BUY" {
			side = OrderBuy
		}
		if settings.AllowSell && analysis.Score <= settings.SellScore && analysis.Action == "SELL" {
			side = OrderSell
		}
		if side == "" || hasOrderToday(orders, symbol, side, now) {
			continue
		}
		price := valueOrZero(analysis.Price)
		if price <= 0 {
			continue
		}
		quantity := 0
		if side == OrderBuy {
			budget := math.Min(settings.MaxOrderValue, account.Cash*0.95)
			quantity = int(math.Floor(budget/price/100)) * 100
		} else {
			position := positionBySymbol[symbol]
			quantity = position.Available
			if quantity <= 0 {
				quantity = position.Quantity
			}
		}
		if quantity <= 0 {
			continue
		}
		order, placeErr := m.PlaceOrder(ctx, domain.OrderRequest{
			ClientOrderID: id.New("cust"),
			Symbol:        symbol,
			Side:          side,
			OrderType:     OrderMarket,
			Quantity:      quantity,
			Reason:        fmt.Sprintf("托管策略: 评分 %d，置信度 %.0f%%", analysis.Score, analysis.Confidence*100),
		}, "custody", actor)
		if placeErr != nil {
			failures = append(failures, symbol+" 下单失败: "+placeErr.Error())
			continue
		}
		placed = append(placed, order)
		account = m.Account(ctx)
	}
	result := fmt.Sprintf("检查 %d 只，提交 %d 笔委托", len(settings.Symbols), len(placed))
	if len(failures) > 0 {
		result += "；" + strings.Join(failures, "；")
	}
	m.recordCustodyResult(now, result)
	m.store.RecordAudit("custody", "托管执行", actor, "custody-engine", result)
	return placed, nil
}

func (m *Manager) StartCustodyLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			settings := m.CustodySettings()
			if !settings.Enabled {
				continue
			}
			now := m.now().In(m.location)
			if !marketOpen(now) {
				continue
			}
			if settings.LastRunAt != nil && now.Sub(*settings.LastRunAt) < time.Duration(settings.IntervalSeconds)*time.Second {
				continue
			}
			if _, err := m.RunCustodyOnce(ctx, "custody-engine", false); err != nil {
				m.logger.Warn("托管交易执行失败", "error", err)
			}
		}
	}
}

func (m *Manager) recordCustodyResult(at time.Time, result string) {
	_ = m.store.UpdateTrading(func(state *store.TradingState) error {
		state.Custody.LastRunAt = &at
		state.Custody.LastResult = result
		return nil
	})
}

func normalizeSymbols(symbols []string) []string {
	seen := make(map[string]bool, len(symbols))
	out := make([]string, 0, len(symbols))
	for _, symbol := range symbols {
		symbol = strings.TrimSpace(symbol)
		if len(symbol) != 6 {
			continue
		}
		if _, err := strconv.Atoi(symbol); err != nil {
			continue
		}
		if !seen[symbol] {
			seen[symbol] = true
			out = append(out, symbol)
		}
	}
	return out
}

func hasOrderToday(orders []domain.Order, symbol, side string, now time.Time) bool {
	for _, order := range orders {
		if order.Symbol != symbol || order.Side != side {
			continue
		}
		if order.Status != OrderPending && order.Status != OrderFilled {
			continue
		}
		created := order.CreatedAt.In(now.Location())
		if created.Year() == now.Year() && created.YearDay() == now.YearDay() {
			return true
		}
	}
	return false
}

func marketOpen(now time.Time) bool {
	if now.Weekday() == time.Saturday || now.Weekday() == time.Sunday {
		return false
	}
	minutes := now.Hour()*60 + now.Minute()
	return (minutes >= 9*60+30 && minutes <= 11*60+30) ||
		(minutes >= 13*60 && minutes <= 15*60)
}

func envBool(name string) bool {
	value := strings.ToLower(strings.TrimSpace(os.Getenv(name)))
	return value == "1" || value == "true" || value == "yes"
}
