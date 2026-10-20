package trading

import (
	"context"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

type PriceSource interface {
	Quote(ctx context.Context, symbol string) (domain.Quote, error)
}

type Broker interface {
	Name() string
	Mode() string
	Account(ctx context.Context) (domain.Account, error)
	PlaceOrder(ctx context.Context, request domain.OrderRequest, source, actor string) (domain.Order, error)
	CancelOrder(ctx context.Context, orderID, actor string) (domain.Order, error)
	Orders(ctx context.Context, limit int) ([]domain.Order, error)
}
