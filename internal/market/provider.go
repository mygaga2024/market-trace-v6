package market

import (
	"context"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

type Provider interface {
	Name() string
	Quotes(ctx context.Context, symbols []string) ([]domain.Quote, error)
	Indices(ctx context.Context) ([]domain.IndexQuote, error)
	Kline(ctx context.Context, symbol string, limit int) ([]domain.Bar, error)
}

type snapshotCache struct {
	quotes    []domain.Quote
	indices   []domain.IndexQuote
	fetchedAt time.Time
	err       error
}

func movingAverage(values []float64, period int) (float64, bool) {
	if period <= 0 || len(values) < period {
		return 0, false
	}
	var sum float64
	for _, value := range values[len(values)-period:] {
		sum += value
	}
	return sum / float64(period), true
}
