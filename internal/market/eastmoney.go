package market

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

const (
	eastmoneyQuoteURL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
	eastmoneyKlineURL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
)

var indexSecIDs = []struct {
	code string
	name string
	id   string
}{
	{"000001", "上证指数", "1.000001"},
	{"399001", "深证成指", "0.399001"},
	{"399006", "创业板指", "0.399006"},
	{"000688", "科创50", "1.000688"},
	{"000300", "沪深300", "1.000300"},
}

type EastmoneyProvider struct {
	client *http.Client
}

func NewEastmoneyProvider(client *http.Client) *EastmoneyProvider {
	if client == nil {
		client = &http.Client{Timeout: 8 * time.Second}
	}
	return &EastmoneyProvider{client: client}
}

func (p *EastmoneyProvider) Name() string {
	return "eastmoney-live"
}

func (p *EastmoneyProvider) Quotes(ctx context.Context, symbols []string) ([]domain.Quote, error) {
	if len(symbols) == 0 {
		return []domain.Quote{}, nil
	}
	secids := make([]string, 0, len(symbols))
	for _, symbol := range symbols {
		secids = append(secids, stockSecID(symbol))
	}

	rows, err := p.fetchQuoteRows(ctx, secids)
	if err != nil {
		return nil, err
	}
	byCode := make(map[string]quoteRow, len(rows))
	for _, row := range rows {
		byCode[row.Code] = row
	}

	now := time.Now()
	out := make([]domain.Quote, 0, len(symbols))
	for _, symbol := range symbols {
		row, ok := byCode[symbol]
		if !ok {
			out = append(out, domain.Quote{Symbol: symbol, UpdatedAt: now, Stale: true})
			continue
		}
		out = append(out, quoteFromRow(row, now))
	}
	return out, nil
}

func (p *EastmoneyProvider) Indices(ctx context.Context) ([]domain.IndexQuote, error) {
	secids := make([]string, 0, len(indexSecIDs))
	for _, item := range indexSecIDs {
		secids = append(secids, item.id)
	}
	rows, err := p.fetchQuoteRows(ctx, secids)
	if err != nil {
		return nil, err
	}
	byCode := make(map[string]quoteRow, len(rows))
	for _, row := range rows {
		byCode[row.Code] = row
	}
	out := make([]domain.IndexQuote, 0, len(indexSecIDs))
	for _, item := range indexSecIDs {
		row, ok := byCode[item.code]
		if !ok {
			out = append(out, domain.IndexQuote{Code: item.code, Name: item.name})
			continue
		}
		name := row.Name
		if name == "" {
			name = item.name
		}
		out = append(out, domain.IndexQuote{
			Code:      item.code,
			Name:      name,
			Price:     row.Price.ptr(),
			Change:    row.Change.ptr(),
			ChangePct: row.ChangePct.ptr(),
		})
	}
	return out, nil
}

func (p *EastmoneyProvider) Kline(ctx context.Context, symbol string, limit int) ([]domain.Bar, error) {
	if limit < 30 {
		limit = 30
	}
	if limit > 500 {
		limit = 500
	}
	params := url.Values{}
	params.Set("secid", stockSecID(symbol))
	params.Set("klt", "101")
	params.Set("fqt", "1")
	params.Set("lmt", strconv.Itoa(limit))
	params.Set("end", "20500101")
	params.Set("fields1", "f1,f2,f3,f4,f5,f6")
	params.Set("fields2", "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61")

	var payload struct {
		Data *struct {
			Code   string   `json:"code"`
			Name   string   `json:"name"`
			Klines []string `json:"klines"`
		} `json:"data"`
	}
	if err := p.getJSON(ctx, eastmoneyKlineURL+"?"+params.Encode(), &payload); err != nil {
		return nil, err
	}
	if payload.Data == nil || len(payload.Data.Klines) == 0 {
		return nil, fmt.Errorf("股票 %s 暂无 K 线数据", symbol)
	}

	bars := make([]domain.Bar, 0, len(payload.Data.Klines))
	for _, line := range payload.Data.Klines {
		fields := strings.Split(line, ",")
		if len(fields) < 7 {
			continue
		}
		open, err1 := strconv.ParseFloat(fields[1], 64)
		closePrice, err2 := strconv.ParseFloat(fields[2], 64)
		high, err3 := strconv.ParseFloat(fields[3], 64)
		low, err4 := strconv.ParseFloat(fields[4], 64)
		volume, err5 := strconv.ParseFloat(fields[5], 64)
		amount, err6 := strconv.ParseFloat(fields[6], 64)
		if err1 != nil || err2 != nil || err3 != nil || err4 != nil || err5 != nil || err6 != nil {
			continue
		}
		bars = append(bars, domain.Bar{
			Date:   fields[0],
			Open:   open,
			Close:  closePrice,
			High:   high,
			Low:    low,
			Volume: volume,
			Amount: amount,
		})
	}
	if len(bars) < 5 {
		return nil, fmt.Errorf("股票 %s K 线数据不足", symbol)
	}
	return bars, nil
}

func (p *EastmoneyProvider) fetchQuoteRows(ctx context.Context, secids []string) ([]quoteRow, error) {
	params := url.Values{}
	params.Set("fltt", "2")
	params.Set("secids", strings.Join(secids, ","))
	params.Set("fields", "f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18")

	var payload struct {
		Data *struct {
			Diff []quoteRow `json:"diff"`
		} `json:"data"`
	}
	if err := p.getJSON(ctx, eastmoneyQuoteURL+"?"+params.Encode(), &payload); err != nil {
		return nil, err
	}
	if payload.Data == nil {
		return nil, errors.New("行情服务返回空数据")
	}
	return payload.Data.Diff, nil
}

func (p *EastmoneyProvider) getJSON(ctx context.Context, endpoint string, target any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 MarketTrace/2.0")
	req.Header.Set("Accept", "application/json")
	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("请求行情服务失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("行情服务返回 HTTP %d", resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return fmt.Errorf("读取行情响应失败: %w", err)
	}
	if err := json.Unmarshal(raw, target); err != nil {
		return fmt.Errorf("解析行情响应失败: %w", err)
	}
	return nil
}

type quoteRow struct {
	Price     flexFloat `json:"f2"`
	ChangePct flexFloat `json:"f3"`
	Change    flexFloat `json:"f4"`
	Volume    flexFloat `json:"f5"`
	Amount    flexFloat `json:"f6"`
	Code      string    `json:"f12"`
	Name      string    `json:"f14"`
	High      flexFloat `json:"f15"`
	Low       flexFloat `json:"f16"`
	Open      flexFloat `json:"f17"`
	PrevClose flexFloat `json:"f18"`
}

type flexFloat struct {
	value float64
	valid bool
}

func (f *flexFloat) UnmarshalJSON(raw []byte) error {
	text := strings.TrimSpace(string(raw))
	if text == "null" || text == `""` || text == `"-"` {
		return nil
	}
	text = strings.Trim(text, `"`)
	if text == "-" || text == "" {
		return nil
	}
	value, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return nil
	}
	f.value = value
	f.valid = true
	return nil
}

func (f flexFloat) ptr() *float64 {
	if !f.valid {
		return nil
	}
	value := f.value
	return &value
}

func quoteFromRow(row quoteRow, at time.Time) domain.Quote {
	return domain.Quote{
		Symbol:    row.Code,
		Name:      row.Name,
		Price:     row.Price.ptr(),
		PrevClose: row.PrevClose.ptr(),
		Open:      row.Open.ptr(),
		High:      row.High.ptr(),
		Low:       row.Low.ptr(),
		Change:    row.Change.ptr(),
		ChangePct: row.ChangePct.ptr(),
		Volume:    row.Volume.ptr(),
		Amount:    row.Amount.ptr(),
		UpdatedAt: at,
	}
}

func stockSecID(symbol string) string {
	if len(symbol) > 0 && strings.Contains("569", symbol[:1]) {
		return "1." + symbol
	}
	return "0." + symbol
}
