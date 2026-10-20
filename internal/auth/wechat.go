package auth

import (
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

const (
	wechatAuthorizeURL = "https://open.weixin.qq.com/connect/qrconnect"
	wechatTokenURL     = "https://api.weixin.qq.com/sns/oauth2/access_token"
	wechatUserInfoURL  = "https://api.weixin.qq.com/sns/userinfo"
)

type WeChatConfig struct {
	AppID        string
	AppSecret    string
	RedirectURL  string
	AuthorizeURL string
	TokenURL     string
	UserInfoURL  string
}

func WeChatConfigFromEnv() WeChatConfig {
	return WeChatConfig{
		AppID:       strings.TrimSpace(os.Getenv("WECHAT_APP_ID")),
		AppSecret:   strings.TrimSpace(os.Getenv("WECHAT_APP_SECRET")),
		RedirectURL: strings.TrimSpace(os.Getenv("WECHAT_REDIRECT_URL")),
	}
}

type WeChatOAuth struct {
	config WeChatConfig
	client *http.Client

	mu     sync.Mutex
	states map[string]time.Time
	now    func() time.Time
}

type WeChatIdentity struct {
	Provider  string
	Subject   string
	OpenID    string
	UnionID   string
	Nickname  string
	AvatarURL string
}

func NewWeChatOAuth(config WeChatConfig) *WeChatOAuth {
	if config.AuthorizeURL == "" {
		config.AuthorizeURL = wechatAuthorizeURL
	}
	if config.TokenURL == "" {
		config.TokenURL = wechatTokenURL
	}
	if config.UserInfoURL == "" {
		config.UserInfoURL = wechatUserInfoURL
	}
	return &WeChatOAuth{
		config: config,
		client: &http.Client{Timeout: 12 * time.Second},
		states: make(map[string]time.Time),
		now:    time.Now,
	}
}

func (w *WeChatOAuth) Name() string {
	return "微信扫码登录"
}

func (w *WeChatOAuth) Configured() bool {
	if w.config.AppID == "" || w.config.AppSecret == "" || w.config.RedirectURL == "" {
		return false
	}
	redirect, err := url.Parse(w.config.RedirectURL)
	return err == nil && redirect.Scheme != "" && redirect.Host != ""
}

func (w *WeChatOAuth) MissingReason() string {
	if w.Configured() {
		return ""
	}
	return "需配置微信开放平台网站应用 AppID、AppSecret 和已审核的回调域名。"
}

func (w *WeChatOAuth) StartURL() (string, error) {
	if !w.Configured() {
		return "", errors.New(w.MissingReason())
	}
	state, err := randomURLToken(24)
	if err != nil {
		return "", err
	}
	w.mu.Lock()
	now := w.now()
	for key, expiry := range w.states {
		if now.After(expiry) {
			delete(w.states, key)
		}
	}
	w.states[state] = now.Add(10 * time.Minute)
	w.mu.Unlock()

	authURL, err := url.Parse(w.config.AuthorizeURL)
	if err != nil {
		return "", err
	}
	query := authURL.Query()
	query.Set("appid", w.config.AppID)
	query.Set("redirect_uri", w.config.RedirectURL)
	query.Set("response_type", "code")
	query.Set("scope", "snsapi_login")
	query.Set("state", state)
	authURL.RawQuery = query.Encode()
	return authURL.String() + "#wechat_redirect", nil
}

func (w *WeChatOAuth) Exchange(code, state string) (WeChatIdentity, error) {
	if !w.Configured() {
		return WeChatIdentity{}, errors.New(w.MissingReason())
	}
	w.mu.Lock()
	expiry, ok := w.states[state]
	delete(w.states, state)
	w.mu.Unlock()
	if !ok || code == "" || w.now().After(expiry) {
		return WeChatIdentity{}, errors.New("微信登录状态已失效，请重新扫码")
	}

	params := url.Values{}
	params.Set("appid", w.config.AppID)
	params.Set("secret", w.config.AppSecret)
	params.Set("code", code)
	params.Set("grant_type", "authorization_code")
	var token struct {
		AccessToken string `json:"access_token"`
		OpenID      string `json:"openid"`
		UnionID     string `json:"unionid"`
		ErrCode     int    `json:"errcode"`
		ErrMsg      string `json:"errmsg"`
	}
	if err := w.getJSON(w.config.TokenURL+"?"+params.Encode(), &token); err != nil {
		return WeChatIdentity{}, err
	}
	if token.ErrCode != 0 {
		return WeChatIdentity{}, fmt.Errorf("微信授权失败(%d): %s", token.ErrCode, token.ErrMsg)
	}
	if token.AccessToken == "" || token.OpenID == "" {
		return WeChatIdentity{}, errors.New("微信授权响应缺少 access_token 或 openid")
	}

	infoParams := url.Values{}
	infoParams.Set("access_token", token.AccessToken)
	infoParams.Set("openid", token.OpenID)
	infoParams.Set("lang", "zh_CN")
	var profile struct {
		OpenID   string `json:"openid"`
		Nickname string `json:"nickname"`
		HeadImg  string `json:"headimgurl"`
		UnionID  string `json:"unionid"`
		ErrCode  int    `json:"errcode"`
		ErrMsg   string `json:"errmsg"`
	}
	if err := w.getJSON(w.config.UserInfoURL+"?"+infoParams.Encode(), &profile); err != nil {
		return WeChatIdentity{}, err
	}
	if profile.ErrCode != 0 {
		return WeChatIdentity{}, fmt.Errorf("读取微信用户失败(%d): %s", profile.ErrCode, profile.ErrMsg)
	}
	unionID := profile.UnionID
	if unionID == "" {
		unionID = token.UnionID
	}
	subject := unionID
	if subject == "" {
		subject = profile.OpenID
	}
	if subject == "" {
		subject = token.OpenID
	}
	nickname := strings.TrimSpace(profile.Nickname)
	if nickname == "" {
		nickname = "微信用户"
	}
	return WeChatIdentity{
		Provider:  "wechat",
		Subject:   subject,
		OpenID:    profile.OpenID,
		UnionID:   unionID,
		Nickname:  nickname,
		AvatarURL: profile.HeadImg,
	}, nil
}

func (w *WeChatOAuth) getJSON(endpoint string, target any) error {
	response, err := w.client.Get(endpoint)
	if err != nil {
		return fmt.Errorf("连接微信开放平台失败: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("微信开放平台返回 HTTP %d", response.StatusCode)
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(target); err != nil {
		return fmt.Errorf("解析微信开放平台响应失败: %w", err)
	}
	return nil
}
