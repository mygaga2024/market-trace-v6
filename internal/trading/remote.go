package trading

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/domain"
)

type RemoteConfig struct {
	BaseURL        string
	KeyID          string
	Secret         string
	AccountID      string
	AllowPlainHTTP bool
}

func RemoteConfigFromEnv() RemoteConfig {
	allowHTTP := strings.EqualFold(strings.TrimSpace(os.Getenv("BROKER_GATEWAY_ALLOW_HTTP")), "true")
	return RemoteConfig{
		BaseURL:        strings.TrimRight(strings.TrimSpace(os.Getenv("BROKER_GATEWAY_URL")), "/"),
		KeyID:          strings.TrimSpace(os.Getenv("BROKER_GATEWAY_KEY_ID")),
		Secret:         strings.TrimSpace(os.Getenv("BROKER_GATEWAY_SECRET")),
		AccountID:      strings.TrimSpace(os.Getenv("BROKER_ACCOUNT_ID")),
		AllowPlainHTTP: allowHTTP,
	}
}

type RemoteBroker struct {
	config RemoteConfig
	client *http.Client
}

func NewRemoteBroker(config RemoteConfig) *RemoteBroker {
	return &RemoteBroker{
		config: config,
		client: &http.Client{Timeout: 15 * time.Second},
	}
}

func (b *RemoteBroker) Name() string { return "Official Broker Gateway" }
func (b *RemoteBroker) Mode() string { return "live" }

func (b *RemoteBroker) Configured() bool {
	if b.config.BaseURL == "" || b.config.KeyID == "" || b.config.Secret == "" || b.config.AccountID == "" {
		return false
	}
	parsed, err := url.Parse(b.config.BaseURL)
	if err != nil || parsed.Host == "" {
		return false
	}
	if parsed.Scheme == "https" {
		return true
	}
	if parsed.Scheme == "http" && (b.config.AllowPlainHTTP || isLoopback(parsed.Hostname())) {
		return true
	}
	return false
}

func (b *RemoteBroker) ConfigError() string {
	if b.config.BaseURL == "" || b.config.KeyID == "" || b.config.Secret == "" || b.config.AccountID == "" {
		return "未配置 BROKER_GATEWAY_URL / KEY_ID / SECRET / ACCOUNT_ID"
	}
	parsed, err := url.Parse(b.config.BaseURL)
	if err != nil || parsed.Host == "" {
		return "BROKER_GATEWAY_URL 无效"
	}
	if parsed.Scheme != "https" && !(parsed.Scheme == "http" && (b.config.AllowPlainHTTP || isLoopback(parsed.Hostname()))) {
		return "券商网关必须使用 HTTPS；内网明文 HTTP 需显式设置 BROKER_GATEWAY_ALLOW_HTTP=true"
	}
	return "券商网关配置不完整"
}

func (b *RemoteBroker) Account(ctx context.Context) (domain.Account, error) {
	var account domain.Account
	path := "/v1/account?account_id=" + url.QueryEscape(b.config.AccountID)
	if err := b.do(ctx, http.MethodGet, path, nil, &account); err != nil {
		return domain.Account{}, err
	}
	account.Mode = "live"
	account.Broker = b.Name()
	return account, nil
}

func (b *RemoteBroker) PlaceOrder(ctx context.Context, request domain.OrderRequest, source, actor string) (domain.Order, error) {
	request, err := validateOrderRequest(request)
	if err != nil {
		return domain.Order{}, err
	}
	payload := map[string]any{
		"account_id": b.config.AccountID,
		"source":     source,
		"actor":      actor,
		"order":      request,
	}
	var order domain.Order
	if err := b.do(ctx, http.MethodPost, "/v1/orders", payload, &order); err != nil {
		return domain.Order{}, err
	}
	order.Mode = "live"
	return order, nil
}

func (b *RemoteBroker) CancelOrder(ctx context.Context, orderID, actor string) (domain.Order, error) {
	payload := map[string]any{
		"account_id": b.config.AccountID,
		"actor":      actor,
	}
	var order domain.Order
	path := "/v1/orders/" + url.PathEscape(orderID) + "/cancel"
	if err := b.do(ctx, http.MethodPost, path, payload, &order); err != nil {
		return domain.Order{}, err
	}
	order.Mode = "live"
	return order, nil
}

func (b *RemoteBroker) Orders(ctx context.Context, limit int) ([]domain.Order, error) {
	if limit <= 0 {
		limit = 50
	}
	path := "/v1/orders?account_id=" + url.QueryEscape(b.config.AccountID) + "&limit=" + strconv.Itoa(limit)
	var payload struct {
		Items []domain.Order `json:"items"`
	}
	if err := b.do(ctx, http.MethodGet, path, nil, &payload); err != nil {
		return nil, err
	}
	for i := range payload.Items {
		payload.Items[i].Mode = "live"
	}
	return payload.Items, nil
}

func (b *RemoteBroker) do(ctx context.Context, method, path string, body any, target any) error {
	if !b.Configured() {
		return errors.New(b.ConfigError())
	}
	var raw []byte
	var err error
	if body != nil {
		raw, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, b.config.BaseURL+path, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	timestamp := strconv.FormatInt(time.Now().Unix(), 10)
	signature := signRequest(b.config.Secret, timestamp, method, path, raw)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-MT6-Timestamp", timestamp)
	req.Header.Set("X-MT6-Key", b.config.KeyID)
	req.Header.Set("X-MT6-Signature", signature)
	resp, err := b.client.Do(req)
	if err != nil {
		return fmt.Errorf("连接券商网关失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		rawResp, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
		return fmt.Errorf("券商网关返回 HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(rawResp)))
	}
	if target == nil {
		return nil
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(target); err != nil {
		return fmt.Errorf("解析券商网关响应失败: %w", err)
	}
	return nil
}

func signRequest(secret, timestamp, method, path string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(timestamp))
	_, _ = mac.Write([]byte("\n"))
	_, _ = mac.Write([]byte(strings.ToUpper(method)))
	_, _ = mac.Write([]byte("\n"))
	_, _ = mac.Write([]byte(path))
	_, _ = mac.Write([]byte("\n"))
	_, _ = mac.Write(body)
	return hex.EncodeToString(mac.Sum(nil))
}

func isLoopback(host string) bool {
	return host == "127.0.0.1" || host == "::1" || host == "localhost"
}
