package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

type OAuthConfig struct {
	Name         string
	ClientID     string
	ClientSecret string
	AuthURL      string
	TokenURL     string
	UserInfoURL  string
	RedirectURL  string
	Scope        string
}

type OAuthProvider struct {
	config OAuthConfig
	client *http.Client

	mu     sync.Mutex
	states map[string]oauthState
	now    func() time.Time
}

type oauthState struct {
	Verifier  string
	ExpiresAt time.Time
}

type ExternalIdentity struct {
	Provider    string
	Subject     string
	Username    string
	DisplayName string
}

func OAuthConfigFromEnv() OAuthConfig {
	cfg := OAuthConfig{
		Name:         strings.TrimSpace(os.Getenv("QR_LOGIN_PROVIDER_NAME")),
		ClientID:     strings.TrimSpace(os.Getenv("QR_LOGIN_CLIENT_ID")),
		ClientSecret: strings.TrimSpace(os.Getenv("QR_LOGIN_CLIENT_SECRET")),
		AuthURL:      strings.TrimSpace(os.Getenv("QR_LOGIN_AUTH_URL")),
		TokenURL:     strings.TrimSpace(os.Getenv("QR_LOGIN_TOKEN_URL")),
		UserInfoURL:  strings.TrimSpace(os.Getenv("QR_LOGIN_USERINFO_URL")),
		RedirectURL:  strings.TrimSpace(os.Getenv("QR_LOGIN_REDIRECT_URL")),
		Scope:        strings.TrimSpace(os.Getenv("QR_LOGIN_SCOPE")),
	}
	if cfg.Name == "" {
		cfg.Name = "官方开放平台"
	}
	if cfg.Scope == "" {
		cfg.Scope = "openid profile"
	}
	return cfg
}

func NewOAuthProvider(cfg OAuthConfig) *OAuthProvider {
	return &OAuthProvider{
		config: cfg,
		client: &http.Client{Timeout: 12 * time.Second},
		states: make(map[string]oauthState),
		now:    time.Now,
	}
}

func (p *OAuthProvider) Name() string {
	return p.config.Name
}

func (p *OAuthProvider) Configured() bool {
	return p.config.ClientID != "" &&
		p.config.ClientSecret != "" &&
		p.config.AuthURL != "" &&
		p.config.TokenURL != "" &&
		p.config.UserInfoURL != "" &&
		p.config.RedirectURL != ""
}

func (p *OAuthProvider) MissingReason() string {
	if p.Configured() {
		return ""
	}
	return "尚未配置官方 OAuth/OIDC 参数；为防止伪造扫码和违规接入，未配置时不会生成登录二维码。"
}

func (p *OAuthProvider) StartURL() (string, error) {
	if !p.Configured() {
		return "", errors.New(p.MissingReason())
	}
	state, err := randomURLToken(24)
	if err != nil {
		return "", err
	}
	verifier, err := randomURLToken(48)
	if err != nil {
		return "", err
	}
	challengeRaw := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(challengeRaw[:])

	p.mu.Lock()
	now := p.now()
	for key, item := range p.states {
		if now.After(item.ExpiresAt) {
			delete(p.states, key)
		}
	}
	p.states[state] = oauthState{Verifier: verifier, ExpiresAt: now.Add(10 * time.Minute)}
	p.mu.Unlock()

	authURL, err := url.Parse(p.config.AuthURL)
	if err != nil {
		return "", fmt.Errorf("OAuth 授权地址无效: %w", err)
	}
	query := authURL.Query()
	query.Set("response_type", "code")
	query.Set("client_id", p.config.ClientID)
	query.Set("redirect_uri", p.config.RedirectURL)
	query.Set("scope", p.config.Scope)
	query.Set("state", state)
	query.Set("code_challenge", challenge)
	query.Set("code_challenge_method", "S256")
	authURL.RawQuery = query.Encode()
	return authURL.String(), nil
}

func (p *OAuthProvider) Exchange(code, state string) (ExternalIdentity, error) {
	if !p.Configured() {
		return ExternalIdentity{}, errors.New(p.MissingReason())
	}
	p.mu.Lock()
	item, ok := p.states[state]
	delete(p.states, state)
	p.mu.Unlock()
	if !ok || p.now().After(item.ExpiresAt) || code == "" {
		return ExternalIdentity{}, errors.New("扫码登录状态已失效，请重新发起")
	}

	form := url.Values{}
	form.Set("grant_type", "authorization_code")
	form.Set("code", code)
	form.Set("client_id", p.config.ClientID)
	form.Set("client_secret", p.config.ClientSecret)
	form.Set("redirect_uri", p.config.RedirectURL)
	form.Set("code_verifier", item.Verifier)
	req, err := http.NewRequest(http.MethodPost, p.config.TokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return ExternalIdentity{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	resp, err := p.client.Do(req)
	if err != nil {
		return ExternalIdentity{}, fmt.Errorf("交换扫码授权失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return ExternalIdentity{}, fmt.Errorf("扫码授权服务返回 HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var tokenPayload map[string]any
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&tokenPayload); err != nil {
		return ExternalIdentity{}, fmt.Errorf("解析扫码授权响应失败: %w", err)
	}
	accessToken, _ := tokenPayload["access_token"].(string)
	if accessToken == "" {
		return ExternalIdentity{}, errors.New("扫码授权响应缺少 access_token")
	}

	userReq, err := http.NewRequest(http.MethodGet, p.config.UserInfoURL, nil)
	if err != nil {
		return ExternalIdentity{}, err
	}
	userReq.Header.Set("Authorization", "Bearer "+accessToken)
	userReq.Header.Set("Accept", "application/json")
	userResp, err := p.client.Do(userReq)
	if err != nil {
		return ExternalIdentity{}, fmt.Errorf("读取扫码用户信息失败: %w", err)
	}
	defer userResp.Body.Close()
	if userResp.StatusCode < 200 || userResp.StatusCode >= 300 {
		return ExternalIdentity{}, fmt.Errorf("扫码用户信息服务返回 HTTP %d", userResp.StatusCode)
	}
	var profile map[string]any
	if err := json.NewDecoder(io.LimitReader(userResp.Body, 1<<20)).Decode(&profile); err != nil {
		return ExternalIdentity{}, fmt.Errorf("解析扫码用户信息失败: %w", err)
	}
	subject := firstString(profile, "sub", "openid", "unionid", "user_id", "uid")
	if subject == "" {
		return ExternalIdentity{}, errors.New("扫码用户信息缺少唯一标识")
	}
	username := firstString(profile, "preferred_username", "username", "email", "mobile", "phone_number")
	if username == "" {
		username = "qr_" + subject
	}
	display := firstString(profile, "name", "display_name", "nickname", "preferred_username")
	if display == "" {
		display = username
	}
	return ExternalIdentity{
		Provider:    p.config.Name,
		Subject:     subject,
		Username:    username,
		DisplayName: display,
	}, nil
}

func randomURLToken(length int) (string, error) {
	raw := make([]byte, length)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

func firstString(values map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := values[key].(string); ok && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}
