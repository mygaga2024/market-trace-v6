package trading

import (
	"context"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/id"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

const (
	OrderBuy      = "BUY"
	OrderSell     = "SELL"
	OrderMarket   = "MARKET"
	OrderLimit    = "LIMIT"
	OrderFilled   = "FILLED"
	OrderPending  = "PENDING"
	OrderCanceled = "CANCELED"
	OrderRejected = "REJECTED"
)

type PaperBroker struct {
	store  *store.Store
	quotes PriceSource
}

func NewPaperBroker(state *store.Store, quotes PriceSource) *PaperBroker {
	return &PaperBroker{store: state, quotes: quotes}
}

func (b *PaperBroker) Name() string { return "Paper Broker" }
func (b *PaperBroker) Mode() string { return "paper" }

func (b *PaperBroker) Account(ctx context.Context) (domain.Account, error) {
	if err := b.ProcessPending(ctx); err != nil {
		return domain.Account{}, err
	}
	snapshot := b.store.TradingSnapshot()
	positions := make([]domain.Position, 0, len(snapshot.PaperPositions))
	marketValue := 0.0
	dayPnL := 0.0
	for _, position := range snapshot.PaperPositions {
		quote, err := b.quotes.Quote(ctx, position.Symbol)
		if err == nil && quote.Price != nil {
			position.LastPrice = *quote.Price
			position.PrevClose = valueOrZero(quote.PrevClose)
		}
		position.MarketValue = position.LastPrice * float64(position.Quantity)
		position.UnrealizedPnL = (position.LastPrice - position.AvgCost) * float64(position.Quantity)
		if position.AvgCost > 0 {
			position.UnrealizedPct = (position.LastPrice/position.AvgCost - 1) * 100
		}
		if position.PrevClose > 0 {
			dayPnL += (position.LastPrice - position.PrevClose) * float64(position.Quantity)
		}
		marketValue += position.MarketValue
		positions = append(positions, position)
	}
	sort.Slice(positions, func(i, j int) bool {
		return positions[i].MarketValue > positions[j].MarketValue
	})
	return domain.Account{
		Mode:        "paper",
		Broker:      b.Name(),
		Cash:        roundMoney(snapshot.PaperCash),
		MarketValue: roundMoney(marketValue),
		TotalEquity: roundMoney(snapshot.PaperCash + marketValue),
		DayPnL:      roundMoney(dayPnL),
		Positions:   positions,
		UpdatedAt:   time.Now(),
	}, nil
}

func (b *PaperBroker) PlaceOrder(ctx context.Context, request domain.OrderRequest, source, actor string) (domain.Order, error) {
	request, err := validateOrderRequest(request)
	if err != nil {
		return domain.Order{}, err
	}
	if existing, ok := b.store.OrderByClientID(request.ClientOrderID); ok {
		return existing, nil
	}
	quote, err := b.quotes.Quote(ctx, request.Symbol)
	if err != nil {
		return domain.Order{}, err
	}
	if quote.Price == nil || *quote.Price <= 0 {
		return domain.Order{}, errors.New("行情价格不可用，已拒绝模拟委托")
	}
	price := *quote.Price

	now := time.Now()
	order := domain.Order{
		ID:            id.New("ord"),
		ClientOrderID: request.ClientOrderID,
		Symbol:        request.Symbol,
		Name:          quote.Name,
		Side:          request.Side,
		OrderType:     request.OrderType,
		Quantity:      request.Quantity,
		LimitPrice:    request.LimitPrice,
		Status:        OrderPending,
		Mode:          "paper",
		Source:        source,
		Reason:        request.Reason,
		CreatedAt:     now,
		UpdatedAt:     now,
	}
	if order.Name == "" {
		order.Name = request.Symbol
	}
	if marketable(order, price) {
		err = b.store.UpdateTrading(func(state *store.TradingState) error {
			filledAt := time.Now()
			if err := fillPaperOrder(state, &order, price); err != nil {
				return err
			}
			order.Status = OrderFilled
			order.AvgFillPrice = price
			order.FilledQuantity = order.Quantity
			order.FilledAt = &filledAt
			order.UpdatedAt = filledAt
			state.Orders = append([]domain.Order{order}, state.Orders...)
			if len(state.Orders) > 2000 {
				state.Orders = state.Orders[:2000]
			}
			return nil
		})
	} else {
		err = b.store.UpdateTrading(func(state *store.TradingState) error {
			state.Orders = append([]domain.Order{order}, state.Orders...)
			if len(state.Orders) > 2000 {
				state.Orders = state.Orders[:2000]
			}
			return nil
		})
	}
	if err != nil {
		return domain.Order{}, err
	}
	detail := fmt.Sprintf("%s %s %d 股，状态 %s", order.Symbol, order.Side, order.Quantity, order.Status)
	b.store.RecordAudit("trading", "模拟委托", actor, order.ID, detail)
	return order, nil
}

func (b *PaperBroker) CancelOrder(_ context.Context, orderID, actor string) (domain.Order, error) {
	var updated domain.Order
	err := b.store.UpdateTrading(func(state *store.TradingState) error {
		for i := range state.Orders {
			if state.Orders[i].ID != orderID && state.Orders[i].ClientOrderID != orderID {
				continue
			}
			if state.Orders[i].Status != OrderPending {
				return fmt.Errorf("委托状态为 %s，无法撤单", state.Orders[i].Status)
			}
			state.Orders[i].Status = OrderCanceled
			state.Orders[i].UpdatedAt = time.Now()
			updated = state.Orders[i]
			return nil
		}
		return store.ErrNotFound
	})
	if err != nil {
		return domain.Order{}, err
	}
	b.store.RecordAudit("trading", "模拟撤单", actor, updated.ID, "撤销 "+updated.Symbol+" 委托")
	return updated, nil
}

func (b *PaperBroker) Orders(_ context.Context, limit int) ([]domain.Order, error) {
	return b.store.Orders(limit), nil
}

func (b *PaperBroker) ProcessPending(ctx context.Context) error {
	snapshot := b.store.TradingSnapshot()
	pending := make([]domain.Order, 0)
	for _, order := range snapshot.Orders {
		if order.Status == OrderPending {
			pending = append(pending, order)
		}
	}
	if len(pending) == 0 {
		return nil
	}
	var firstErr error
	for _, order := range pending {
		quote, err := b.quotes.Quote(ctx, order.Symbol)
		if err != nil || quote.Price == nil || !marketable(order, *quote.Price) {
			continue
		}
		price := *quote.Price
		err = b.store.UpdateTrading(func(state *store.TradingState) error {
			for i := range state.Orders {
				if state.Orders[i].ID != order.ID || state.Orders[i].Status != OrderPending {
					continue
				}
				if err := fillPaperOrder(state, &state.Orders[i], price); err != nil {
					state.Orders[i].Status = OrderRejected
					state.Orders[i].ErrorMessage = err.Error()
					state.Orders[i].UpdatedAt = time.Now()
					return nil
				}
				now := time.Now()
				state.Orders[i].Status = OrderFilled
				state.Orders[i].FilledQuantity = state.Orders[i].Quantity
				state.Orders[i].AvgFillPrice = price
				state.Orders[i].FilledAt = &now
				state.Orders[i].UpdatedAt = now
			}
			return nil
		})
		if err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func validateOrderRequest(request domain.OrderRequest) (domain.OrderRequest, error) {
	request.Symbol = strings.TrimSpace(request.Symbol)
	request.Side = strings.ToUpper(strings.TrimSpace(request.Side))
	request.OrderType = strings.ToUpper(strings.TrimSpace(request.OrderType))
	request.Reason = strings.TrimSpace(request.Reason)
	if len(request.Symbol) != 6 {
		return request, errors.New("股票代码需为 6 位数字")
	}
	if _, err := strconv.Atoi(request.Symbol); err != nil {
		return request, errors.New("股票代码需为 6 位数字")
	}
	if request.Side != OrderBuy && request.Side != OrderSell {
		return request, errors.New("交易方向必须为 BUY 或 SELL")
	}
	if request.OrderType == "" {
		request.OrderType = OrderMarket
	}
	if request.OrderType != OrderMarket && request.OrderType != OrderLimit {
		return request, errors.New("委托类型必须为 MARKET 或 LIMIT")
	}
	if request.Quantity <= 0 || request.Quantity > 10_000_000 {
		return request, errors.New("委托数量无效")
	}
	if request.Side == OrderBuy && request.Quantity%100 != 0 {
		return request, errors.New("A 股买入数量必须为 100 股的整数倍")
	}
	if request.OrderType == OrderLimit {
		if request.LimitPrice == nil || *request.LimitPrice <= 0 {
			return request, errors.New("限价委托必须填写有效价格")
		}
	} else {
		request.LimitPrice = nil
	}
	if len(request.Reason) > 200 {
		return request, errors.New("委托理由不能超过 200 字")
	}
	if request.ClientOrderID == "" {
		request.ClientOrderID = id.New("cli")
	}
	return request, nil
}

func marketable(order domain.Order, price float64) bool {
	if order.OrderType == OrderMarket {
		return true
	}
	if order.LimitPrice == nil {
		return false
	}
	if order.Side == OrderBuy {
		return price <= *order.LimitPrice
	}
	return price >= *order.LimitPrice
}

func fillPaperOrder(state *store.TradingState, order *domain.Order, price float64) error {
	amount := price * float64(order.Quantity)
	commission := math.Max(5, amount*0.0003)
	if order.Side == OrderBuy {
		total := amount + commission
		if state.PaperCash+0.000001 < total {
			return fmt.Errorf("模拟账户可用资金不足：需要 %.2f，可用 %.2f", total, state.PaperCash)
		}
		state.PaperCash -= total
		position := state.PaperPositions[order.Symbol]
		if position.Symbol == "" {
			position.Symbol = order.Symbol
			position.Name = order.Name
		}
		newQuantity := position.Quantity + order.Quantity
		position.AvgCost = (position.AvgCost*float64(position.Quantity) + amount) / float64(newQuantity)
		position.Quantity = newQuantity
		position.Available = newQuantity
		position.LastPrice = price
		position.MarketValue = price * float64(newQuantity)
		state.PaperPositions[order.Symbol] = position
		return nil
	}

	position, ok := state.PaperPositions[order.Symbol]
	if !ok || position.Quantity < order.Quantity {
		return errors.New("模拟持仓数量不足")
	}
	stampDuty := amount * 0.0005
	state.PaperCash += amount - commission - stampDuty
	position.Quantity -= order.Quantity
	position.Available = position.Quantity
	position.LastPrice = price
	position.MarketValue = price * float64(position.Quantity)
	if position.Quantity == 0 {
		delete(state.PaperPositions, order.Symbol)
	} else {
		state.PaperPositions[order.Symbol] = position
	}
	return nil
}

func roundMoney(value float64) float64 {
	return math.Round(value*100) / 100
}

func valueOrZero(value *float64) float64 {
	if value == nil {
		return 0
	}
	return *value
}
