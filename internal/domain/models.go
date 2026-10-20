package domain

import "time"

type WatchItem struct {
	Symbol  string    `json:"symbol"`
	Name    string    `json:"name"`
	Notes   string    `json:"notes,omitempty"`
	AddedAt time.Time `json:"added_at"`
}

type Quote struct {
	Symbol    string    `json:"symbol"`
	Name      string    `json:"name"`
	Price     *float64  `json:"price"`
	PrevClose *float64  `json:"prev_close"`
	Open      *float64  `json:"open"`
	High      *float64  `json:"high"`
	Low       *float64  `json:"low"`
	Change    *float64  `json:"change"`
	ChangePct *float64  `json:"change_pct"`
	Volume    *float64  `json:"volume"`
	Amount    *float64  `json:"amount"`
	Stale     bool      `json:"stale"`
	UpdatedAt time.Time `json:"updated_at"`
}

type IndexQuote struct {
	Code      string   `json:"code"`
	Name      string   `json:"name"`
	Price     *float64 `json:"price"`
	Change    *float64 `json:"change"`
	ChangePct *float64 `json:"change_pct"`
}

type Bar struct {
	Date   string  `json:"date"`
	Open   float64 `json:"open"`
	Close  float64 `json:"close"`
	High   float64 `json:"high"`
	Low    float64 `json:"low"`
	Volume float64 `json:"volume"`
	Amount float64 `json:"amount"`
}

type Indicators struct {
	MA5           *float64 `json:"ma5"`
	MA10          *float64 `json:"ma10"`
	MA20          *float64 `json:"ma20"`
	MA60          *float64 `json:"ma60"`
	RSI14         *float64 `json:"rsi14"`
	MACD          *float64 `json:"macd"`
	MACDSignal    *float64 `json:"macd_signal"`
	MACDHistogram *float64 `json:"macd_histogram"`
	KDJ           *float64 `json:"kdj"`
	ATR14         *float64 `json:"atr14"`
	BollUpper     *float64 `json:"boll_upper"`
	BollMiddle    *float64 `json:"boll_middle"`
	BollLower     *float64 `json:"boll_lower"`
	VolumeRatio   *float64 `json:"volume_ratio"`
	Support       *float64 `json:"support"`
	Resistance    *float64 `json:"resistance"`
	Trend         string   `json:"trend"`
}

type Signal struct {
	Key       string  `json:"key"`
	Label     string  `json:"label"`
	Direction string  `json:"direction"`
	Strength  float64 `json:"strength"`
	Evidence  string  `json:"evidence"`
}

type Analysis struct {
	Symbol       string     `json:"symbol"`
	Name         string     `json:"name"`
	Price        *float64   `json:"price"`
	ChangePct    *float64   `json:"change_pct"`
	Score        int        `json:"score"`
	Action       string     `json:"action"`
	Confidence   float64    `json:"confidence"`
	Risk         string     `json:"risk"`
	Summary      string     `json:"summary"`
	Indicators   Indicators `json:"indicators"`
	Signals      []Signal   `json:"signals"`
	Bars         []Bar      `json:"bars"`
	DataComplete bool       `json:"data_complete"`
	DataSource   string     `json:"data_source"`
	GeneratedAt  time.Time  `json:"generated_at"`
}

type Decision struct {
	ID         string    `json:"id"`
	Symbol     string    `json:"symbol"`
	Name       string    `json:"name"`
	Action     string    `json:"action"`
	Score      int       `json:"score"`
	Confidence float64   `json:"confidence"`
	Risk       string    `json:"risk"`
	Summary    string    `json:"summary"`
	CreatedAt  time.Time `json:"created_at"`
}

type AuditEvent struct {
	ID        string    `json:"id"`
	Category  string    `json:"category"`
	Action    string    `json:"action"`
	Actor     string    `json:"actor"`
	Target    string    `json:"target"`
	Detail    string    `json:"detail"`
	CreatedAt time.Time `json:"created_at"`
}

type RiskSettings struct {
	MaxPositionPct float64 `json:"max_position_pct"`
	StopLossPct    float64 `json:"stop_loss_pct"`
	DailyLossPct   float64 `json:"daily_loss_pct"`
	MinConfidence  float64 `json:"min_confidence"`
}

type StrategyToggle struct {
	Key         string `json:"key"`
	Name        string `json:"name"`
	Description string `json:"description"`
	Enabled     bool   `json:"enabled"`
}

type RiskSummary struct {
	RAI             *float64 `json:"rai"`
	Label           string   `json:"label"`
	Level           string   `json:"level"`
	Up              int      `json:"up"`
	Down            int      `json:"down"`
	Flat            int      `json:"flat"`
	AverageChange   *float64 `json:"average_change"`
	PositiveRatio   *float64 `json:"positive_ratio"`
	MissingQuotes   int      `json:"missing_quotes"`
	HighRiskSymbols []string `json:"high_risk_symbols"`
}

type AgentStatus struct {
	Key       string `json:"key"`
	Name      string `json:"name"`
	Role      string `json:"role"`
	Status    string `json:"status"`
	LatencyMS int64  `json:"latency_ms,omitempty"`
	Detail    string `json:"detail"`
}

type StockView struct {
	Symbol      string    `json:"symbol"`
	Name        string    `json:"name"`
	Notes       string    `json:"notes,omitempty"`
	AddedAt     time.Time `json:"added_at"`
	Price       *float64  `json:"price"`
	PrevClose   *float64  `json:"prev_close"`
	Open        *float64  `json:"open"`
	High        *float64  `json:"high"`
	Low         *float64  `json:"low"`
	Change      *float64  `json:"change"`
	ChangePct   *float64  `json:"change_pct"`
	Volume      *float64  `json:"volume"`
	Amount      *float64  `json:"amount"`
	Stale       bool      `json:"stale"`
	UpdatedAt   time.Time `json:"updated_at"`
	Score       *int      `json:"score"`
	Action      string    `json:"action"`
	Risk        string    `json:"risk"`
	LastSummary string    `json:"last_summary,omitempty"`
	Sparkline   []float64 `json:"sparkline,omitempty"`
}

type Overview struct {
	WatchCount    int       `json:"watch_count"`
	PositiveCount int       `json:"positive_count"`
	NegativeCount int       `json:"negative_count"`
	DecisionCount int       `json:"decision_count"`
	AverageScore  *float64  `json:"average_score"`
	RiskLevel     string    `json:"risk_level"`
	DataSource    string    `json:"data_source"`
	LastRefresh   time.Time `json:"last_refresh"`
	LiveMarket    bool      `json:"live_market"`
}

type Dashboard struct {
	Overview    Overview         `json:"overview"`
	Risk        RiskSummary      `json:"risk"`
	Indices     []IndexQuote     `json:"indices"`
	Stocks      []StockView      `json:"stocks"`
	Decisions   []Decision       `json:"decisions"`
	Audits      []AuditEvent     `json:"audits"`
	Agents      []AgentStatus    `json:"agents"`
	Settings    RiskSettings     `json:"settings"`
	Strategies  []StrategyToggle `json:"strategies"`
	GeneratedAt time.Time        `json:"generated_at"`
}
