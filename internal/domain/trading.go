package domain

import "time"

type Position struct {
	Symbol        string  `json:"symbol"`
	Name          string  `json:"name"`
	Quantity      int     `json:"quantity"`
	Available     int     `json:"available"`
	AvgCost       float64 `json:"avg_cost"`
	PrevClose     float64 `json:"prev_close"`
	LastPrice     float64 `json:"last_price"`
	MarketValue   float64 `json:"market_value"`
	UnrealizedPnL float64 `json:"unrealized_pnl"`
	UnrealizedPct float64 `json:"unrealized_pct"`
}

type Account struct {
	Mode        string     `json:"mode"`
	Broker      string     `json:"broker"`
	Cash        float64    `json:"cash"`
	MarketValue float64    `json:"market_value"`
	TotalEquity float64    `json:"total_equity"`
	DayPnL      float64    `json:"day_pnl"`
	Positions   []Position `json:"positions"`
	UpdatedAt   time.Time  `json:"updated_at"`
	Degraded    bool       `json:"degraded"`
	Message     string     `json:"message,omitempty"`
}

type Order struct {
	ID             string     `json:"id"`
	ClientOrderID  string     `json:"client_order_id"`
	BrokerOrderID  string     `json:"broker_order_id,omitempty"`
	Symbol         string     `json:"symbol"`
	Name           string     `json:"name"`
	Side           string     `json:"side"`
	OrderType      string     `json:"order_type"`
	Quantity       int        `json:"quantity"`
	FilledQuantity int        `json:"filled_quantity"`
	LimitPrice     *float64   `json:"limit_price,omitempty"`
	AvgFillPrice   float64    `json:"avg_fill_price"`
	Status         string     `json:"status"`
	Mode           string     `json:"mode"`
	Source         string     `json:"source"`
	Reason         string     `json:"reason,omitempty"`
	ErrorMessage   string     `json:"error_message,omitempty"`
	CreatedAt      time.Time  `json:"created_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
	FilledAt       *time.Time `json:"filled_at,omitempty"`
}

type OrderRequest struct {
	ClientOrderID string   `json:"client_order_id,omitempty"`
	Symbol        string   `json:"symbol"`
	Side          string   `json:"side"`
	OrderType     string   `json:"order_type"`
	Quantity      int      `json:"quantity"`
	LimitPrice    *float64 `json:"limit_price,omitempty"`
	Reason        string   `json:"reason,omitempty"`
}

type CustodySettings struct {
	Enabled         bool       `json:"enabled"`
	Symbols         []string   `json:"symbols"`
	BuyScore        int        `json:"buy_score"`
	SellScore       int        `json:"sell_score"`
	MinConfidence   float64    `json:"min_confidence"`
	MaxOrderValue   float64    `json:"max_order_value"`
	IntervalSeconds int        `json:"interval_seconds"`
	AllowBuy        bool       `json:"allow_buy"`
	AllowSell       bool       `json:"allow_sell"`
	LastRunAt       *time.Time `json:"last_run_at,omitempty"`
	LastResult      string     `json:"last_result,omitempty"`
}

type TradingStatus struct {
	Mode               string `json:"mode"`
	Broker             string `json:"broker"`
	LiveEnabled        bool   `json:"live_enabled"`
	GatewayConfigured  bool   `json:"gateway_configured"`
	CustodyLiveAllowed bool   `json:"custody_live_allowed"`
	Message            string `json:"message"`
}
