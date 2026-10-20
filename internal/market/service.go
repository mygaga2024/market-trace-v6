package market

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

type Service struct {
	provider Provider
	store    *store.Store

	mu         sync.RWMutex
	quoteCache map[string]domain.Quote
	quoteAt    time.Time
	indexCache []domain.IndexQuote
	indexAt    time.Time
	klineCache map[string]cachedBars
	quoteTTL   time.Duration
	klineTTL   time.Duration
}

type cachedBars struct {
	bars []domain.Bar
	at   time.Time
}

func NewService(provider Provider, state *store.Store) *Service {
	return &Service{
		provider:   provider,
		store:      state,
		quoteCache: make(map[string]domain.Quote),
		klineCache: make(map[string]cachedBars),
		quoteTTL:   18 * time.Second,
		klineTTL:   3 * time.Minute,
	}
}

func (s *Service) Dashboard(ctx context.Context) domain.Dashboard {
	watchlist := s.store.Watchlist()
	symbols := make([]string, 0, len(watchlist))
	for _, item := range watchlist {
		symbols = append(symbols, item.Symbol)
	}

	quotes, quoteSource, quoteErr := s.quotes(ctx, symbols)
	indices, indexErr := s.indices(ctx)

	quoteBySymbol := make(map[string]domain.Quote, len(quotes))
	for _, quote := range quotes {
		quoteBySymbol[quote.Symbol] = quote
	}

	stocks := make([]domain.StockView, 0, len(watchlist))
	positive, negative := 0, 0
	var scoreSum float64
	scoreCount := 0
	for _, item := range watchlist {
		quote := quoteBySymbol[item.Symbol]
		if quote.Symbol == "" {
			quote.Symbol = item.Symbol
		}
		if quote.Name == "" {
			quote.Name = item.Name
		}
		if quote.ChangePct != nil {
			if *quote.ChangePct > 0 {
				positive++
			} else if *quote.ChangePct < 0 {
				negative++
			}
		}

		view := domain.StockView{
			Symbol:    item.Symbol,
			Name:      item.Name,
			Notes:     item.Notes,
			AddedAt:   item.AddedAt,
			Price:     quote.Price,
			PrevClose: quote.PrevClose,
			Open:      quote.Open,
			High:      quote.High,
			Low:       quote.Low,
			Change:    quote.Change,
			ChangePct: quote.ChangePct,
			Volume:    quote.Volume,
			Amount:    quote.Amount,
			Stale:     quote.Stale,
			UpdatedAt: quote.UpdatedAt,
			Action:    "待分析",
			Risk:      "未评估",
		}
		if decision, ok := s.store.LatestDecision(item.Symbol); ok {
			score := decision.Score
			view.Score = &score
			view.Action = decision.Action
			view.Risk = decision.Risk
			view.LastSummary = decision.Summary
			scoreSum += float64(decision.Score)
			scoreCount++
		}
		stocks = append(stocks, view)
	}

	risk := summarizeRisk(stocks, indices)
	decisions := s.store.Decisions()
	if len(decisions) > 12 {
		decisions = decisions[:12]
	}

	overview := domain.Overview{
		WatchCount:    len(watchlist),
		PositiveCount: positive,
		NegativeCount: negative,
		DecisionCount: len(s.store.Decisions()),
		RiskLevel:     risk.Level,
		DataSource:    quoteSource,
		LastRefresh:   time.Now(),
		LiveMarket:    quoteSource == s.provider.Name() && quoteErr == nil,
	}
	if scoreCount > 0 {
		avg := math.Round(scoreSum/float64(scoreCount)*10) / 10
		overview.AverageScore = &avg
	}

	agents := []domain.AgentStatus{
		{Key: "market", Name: "行情", Role: "Eastmoney", Status: "running", Detail: "实时指数与自选股行情"},
		{Key: "quant", Name: "量化", Role: "Indicator engine", Status: "running", Detail: "MA / MACD / RSI / KDJ / ATR"},
		{Key: "risk", Name: "风控", Role: "Guardrails", Status: "running", Detail: "仓位、止损与置信度约束"},
		{Key: "memory", Name: "记忆", Role: "Decision journal", Status: "running", Detail: "决策与审计记录已持久化"},
		{Key: "api", Name: "接口", Role: "Go net/http", Status: "running", Detail: "嵌入式 Web 控制台与 JSON API"},
	}
	if quoteErr != nil {
		agents[0].Status = "degraded"
		agents[0].Detail = "行情源暂不可用：" + quoteErr.Error()
	}
	if indexErr != nil {
		agents[0].Status = "degraded"
		agents[0].Detail = "指数行情暂不可用：" + indexErr.Error()
	}

	return domain.Dashboard{
		Overview:    overview,
		Risk:        risk,
		Indices:     indices,
		Stocks:      stocks,
		Decisions:   decisions,
		Audits:      s.store.Audits(30),
		Agents:      agents,
		Settings:    s.store.Settings(),
		Strategies:  s.store.Strategies(),
		GeneratedAt: time.Now(),
	}
}

func (s *Service) Analyze(ctx context.Context, symbol string) (domain.Analysis, error) {
	symbol = normalizeSymbol(symbol)
	if symbol == "" {
		return domain.Analysis{}, errors.New("请提供 6 位股票代码")
	}
	bars, err := s.kline(ctx, symbol, 140)
	if err != nil {
		return domain.Analysis{}, err
	}
	result := analyzeBars(bars, s.store.EnabledStrategies())

	name := ""
	for _, item := range s.store.Watchlist() {
		if item.Symbol == symbol {
			name = item.Name
			break
		}
	}
	if name == "" {
		name = symbol
	}

	var price, changePct *float64
	quotes, _, quoteErr := s.quotes(ctx, []string{symbol})
	if quoteErr == nil && len(quotes) > 0 {
		price = quotes[0].Price
		changePct = quotes[0].ChangePct
		if quotes[0].Name != "" {
			name = quotes[0].Name
		}
	}
	if price == nil {
		value := bars[len(bars)-1].Close
		price = &value
		if len(bars) >= 2 && bars[len(bars)-2].Close != 0 {
			change := math.Round((bars[len(bars)-1].Close-bars[len(bars)-2].Close)/bars[len(bars)-2].Close*10000) / 100
			changePct = &change
		}
	}

	chartBars := bars
	if len(chartBars) > 80 {
		chartBars = chartBars[len(chartBars)-80:]
	}
	analysis := domain.Analysis{
		Symbol:       symbol,
		Name:         name,
		Price:        price,
		ChangePct:    changePct,
		Score:        result.Score,
		Action:       result.Action,
		Confidence:   result.Confidence,
		Risk:         result.Risk,
		Summary:      result.Summary,
		Indicators:   result.Indicators,
		Signals:      result.Signals,
		Bars:         chartBars,
		DataComplete: result.Complete,
		DataSource:   s.provider.Name(),
		GeneratedAt:  time.Now(),
	}
	if err := s.store.RecordAnalysis(analysis); err != nil {
		return domain.Analysis{}, fmt.Errorf("保存决策失败: %w", err)
	}
	return analysis, nil
}

func (s *Service) Quote(ctx context.Context, symbol string) (domain.Quote, error) {
	symbol = normalizeSymbol(symbol)
	if symbol == "" {
		return domain.Quote{}, errors.New("请提供 6 位股票代码")
	}
	quotes, _, err := s.quotes(ctx, []string{symbol})
	if err != nil {
		return domain.Quote{}, err
	}
	if len(quotes) == 0 || quotes[0].Price == nil {
		return domain.Quote{}, fmt.Errorf("股票 %s 暂无可用实时价格", symbol)
	}
	return quotes[0], nil
}

func (s *Service) Health(ctx context.Context) map[string]any {
	start := time.Now()
	_, err := s.provider.Indices(ctx)
	status := "ok"
	if err != nil {
		status = "degraded"
	}
	return map[string]any{
		"status":            status,
		"service":           "market-trace-go",
		"version":           "2.2.0",
		"time":              time.Now(),
		"market_source":     s.provider.Name(),
		"market_latency_ms": time.Since(start).Milliseconds(),
		"error":             errorString(err),
	}
}

func (s *Service) quotes(ctx context.Context, symbols []string) ([]domain.Quote, string, error) {
	if len(symbols) == 0 {
		return []domain.Quote{}, s.provider.Name(), nil
	}
	now := time.Now()
	s.mu.RLock()
	cacheReady := now.Sub(s.quoteAt) < s.quoteTTL && len(s.quoteCache) > 0
	if cacheReady {
		for _, symbol := range symbols {
			if _, ok := s.quoteCache[symbol]; !ok {
				cacheReady = false
				break
			}
		}
	}
	if cacheReady {
		out := s.copyCachedQuotes(symbols)
		s.mu.RUnlock()
		return out, s.provider.Name(), nil
	}
	s.mu.RUnlock()

	quotes, err := s.provider.Quotes(ctx, symbols)
	if err != nil {
		s.mu.RLock()
		defer s.mu.RUnlock()
		if len(s.quoteCache) > 0 {
			out := make([]domain.Quote, 0, len(symbols))
			for _, symbol := range symbols {
				quote, ok := s.quoteCache[symbol]
				if !ok {
					quote = domain.Quote{Symbol: symbol}
				}
				quote.Stale = true
				out = append(out, quote)
			}
			return out, "stale-cache", err
		}
		return nil, "unavailable", err
	}

	s.mu.Lock()
	s.quoteCache = make(map[string]domain.Quote, len(quotes))
	for _, quote := range quotes {
		s.quoteCache[quote.Symbol] = quote
	}
	s.quoteAt = now
	s.mu.Unlock()
	return quotes, s.provider.Name(), nil
}

func (s *Service) copyCachedQuotes(symbols []string) []domain.Quote {
	out := make([]domain.Quote, 0, len(symbols))
	for _, symbol := range symbols {
		quote, ok := s.quoteCache[symbol]
		if !ok {
			quote = domain.Quote{Symbol: symbol}
		}
		out = append(out, quote)
	}
	return out
}

func (s *Service) indices(ctx context.Context) ([]domain.IndexQuote, error) {
	now := time.Now()
	s.mu.RLock()
	if now.Sub(s.indexAt) < s.quoteTTL && len(s.indexCache) > 0 {
		out := make([]domain.IndexQuote, len(s.indexCache))
		copy(out, s.indexCache)
		s.mu.RUnlock()
		return out, nil
	}
	s.mu.RUnlock()

	indices, err := s.provider.Indices(ctx)
	if err != nil {
		s.mu.RLock()
		defer s.mu.RUnlock()
		if len(s.indexCache) > 0 {
			out := make([]domain.IndexQuote, len(s.indexCache))
			copy(out, s.indexCache)
			return out, err
		}
		return []domain.IndexQuote{}, err
	}
	s.mu.Lock()
	s.indexCache = indices
	s.indexAt = now
	s.mu.Unlock()
	return indices, nil
}

func (s *Service) kline(ctx context.Context, symbol string, limit int) ([]domain.Bar, error) {
	now := time.Now()
	s.mu.RLock()
	if cached, ok := s.klineCache[symbol]; ok && now.Sub(cached.at) < s.klineTTL {
		out := make([]domain.Bar, len(cached.bars))
		copy(out, cached.bars)
		s.mu.RUnlock()
		return out, nil
	}
	s.mu.RUnlock()

	bars, err := s.provider.Kline(ctx, symbol, limit)
	if err != nil {
		return nil, err
	}
	s.mu.Lock()
	s.klineCache[symbol] = cachedBars{bars: bars, at: now}
	s.mu.Unlock()
	out := make([]domain.Bar, len(bars))
	copy(out, bars)
	return out, nil
}

func summarizeRisk(stocks []domain.StockView, indices []domain.IndexQuote) domain.RiskSummary {
	summary := domain.RiskSummary{
		Label:           "数据不足",
		Level:           "unknown",
		HighRiskSymbols: []string{},
	}
	var changes []float64
	var indexChanges []float64
	for _, stock := range stocks {
		if stock.ChangePct == nil {
			summary.MissingQuotes++
			continue
		}
		changes = append(changes, *stock.ChangePct)
		switch {
		case *stock.ChangePct > 0:
			summary.Up++
		case *stock.ChangePct < 0:
			summary.Down++
		default:
			summary.Flat++
		}
		if stock.Risk == "高" || stock.Risk == "中高" {
			summary.HighRiskSymbols = append(summary.HighRiskSymbols, stock.Symbol)
		}
	}
	for _, index := range indices {
		if index.ChangePct != nil {
			indexChanges = append(indexChanges, *index.ChangePct)
		}
	}
	if len(changes) == 0 && len(indexChanges) == 0 {
		return summary
	}

	var breadth float64
	if len(changes) > 0 {
		positive := 0
		for _, change := range changes {
			if change > 0 {
				positive++
			}
		}
		breadth = float64(positive) / float64(len(changes))
		avg := math.Round(average(changes)*100) / 100
		summary.AverageChange = &avg
		ratio := math.Round(breadth*10000) / 100
		summary.PositiveRatio = &ratio
	} else {
		breadth = 0.5
	}
	indexMomentum := 0.5
	if len(indexChanges) > 0 {
		avgIndex := average(indexChanges)
		indexMomentum = clampFloat(0.5+avgIndex/6, 0, 1)
	}
	rai := math.Round((breadth*0.62+indexMomentum*0.38)*10000) / 100
	summary.RAI = &rai
	summary.Level = riskLevel(rai)
	switch {
	case rai >= 70:
		summary.Label = "积极"
	case rai >= 55:
		summary.Label = "偏多"
	case rai >= 45:
		summary.Label = "中性"
	case rai >= 30:
		summary.Label = "偏防守"
	default:
		summary.Label = "防守"
	}
	return summary
}

func riskLevel(rai float64) string {
	switch {
	case rai >= 66:
		return "low"
	case rai >= 45:
		return "medium"
	default:
		return "high"
	}
}

func clampFloat(value, low, high float64) float64 {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}

func normalizeSymbol(symbol string) string {
	symbol = trimSpace(symbol)
	if len(symbol) == 8 {
		lower := symbol[:2]
		if lower == "sh" || lower == "sz" {
			symbol = symbol[2:]
		}
	}
	if len(symbol) != 6 {
		return ""
	}
	for _, r := range symbol {
		if r < '0' || r > '9' {
			return ""
		}
	}
	return symbol
}

func trimSpace(value string) string {
	start, end := 0, len(value)
	for start < end && (value[start] == ' ' || value[start] == '\t' || value[start] == '\n' || value[start] == '\r') {
		start++
	}
	for end > start && (value[end-1] == ' ' || value[end-1] == '\t' || value[end-1] == '\n' || value[end-1] == '\r') {
		end--
	}
	return value[start:end]
}

func errorString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
