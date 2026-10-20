package auth

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"
)

func TestPasswordHashAndVerification(t *testing.T) {
	encoded, err := HashPassword("strong-pass-123")
	if err != nil {
		t.Fatalf("HashPassword() error = %v", err)
	}
	if encoded == "strong-pass-123" || encoded == "" {
		t.Fatal("password was not hashed")
	}
	if !VerifyPassword(encoded, "strong-pass-123") {
		t.Fatal("VerifyPassword() rejected the correct password")
	}
	if VerifyPassword(encoded, "wrong-pass-123") {
		t.Fatal("VerifyPassword() accepted an incorrect password")
	}
	if _, err := HashPassword("short"); err == nil {
		t.Fatal("HashPassword() accepted a weak password")
	}
}

func TestNormalizeUsername(t *testing.T) {
	got, err := NormalizeUsername("  Trader_01 ")
	if err != nil || got != "trader_01" {
		t.Fatalf("NormalizeUsername() = %q, %v", got, err)
	}
	if _, err := NormalizeUsername("bad name"); err == nil {
		t.Fatal("NormalizeUsername() accepted a space")
	}
}

func TestSessionManagerExpiry(t *testing.T) {
	manager := NewSessionManager(time.Hour)
	now := time.Now()
	manager.now = func() time.Time { return now }
	session, err := manager.Create("usr-1")
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if _, ok := manager.Get(session.Token); !ok {
		t.Fatal("session missing before expiry")
	}
	manager.now = func() time.Time { return now.Add(2 * time.Hour) }
	if _, ok := manager.Get(session.Token); ok {
		t.Fatal("expired session still valid")
	}
}

func TestAttemptLimiter(t *testing.T) {
	limiter := NewAttemptLimiter(2, time.Minute)
	now := time.Now()
	limiter.now = func() time.Time { return now }
	if !limiter.Allow("ip") || !limiter.Allow("ip") {
		t.Fatal("first two attempts should be allowed")
	}
	if limiter.Allow("ip") {
		t.Fatal("third attempt should be blocked")
	}
	limiter.now = func() time.Time { return now.Add(2 * time.Minute) }
	if !limiter.Allow("ip") {
		t.Fatal("attempt should be allowed after window reset")
	}
}

func TestWeChatOAuthStartAndExchange(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/token", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("code") != "test-code" {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		_, _ = fmt.Fprint(w, `{"access_token":"access-1","openid":"openid-1","unionid":"unionid-1"}`)
	})
	mux.HandleFunc("/userinfo", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("access_token") != "access-1" {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		_, _ = fmt.Fprint(w, `{"openid":"openid-1","nickname":"微信测试用户","headimgurl":"https://example.com/avatar.png","unionid":"unionid-1"}`)
	})
	upstream := httptest.NewServer(mux)
	defer upstream.Close()

	wechat := NewWeChatOAuth(WeChatConfig{
		AppID:        "app-id",
		AppSecret:    "app-secret",
		RedirectURL:  "https://market.example/auth/wechat/callback",
		AuthorizeURL: "https://open.weixin.qq.com/connect/qrconnect",
		TokenURL:     upstream.URL + "/token",
		UserInfoURL:  upstream.URL + "/userinfo",
	})
	startURL, err := wechat.StartURL()
	if err != nil {
		t.Fatalf("StartURL() error = %v", err)
	}
	parsed, err := url.Parse(startURL)
	if err != nil {
		t.Fatalf("parse StartURL: %v", err)
	}
	if parsed.Query().Get("scope") != "snsapi_login" || parsed.Query().Get("appid") != "app-id" {
		t.Fatalf("start query = %s", parsed.RawQuery)
	}
	identity, err := wechat.Exchange("test-code", parsed.Query().Get("state"))
	if err != nil {
		t.Fatalf("Exchange() error = %v", err)
	}
	if identity.Subject != "unionid-1" || identity.Nickname != "微信测试用户" || identity.Provider != "wechat" {
		t.Fatalf("identity = %+v", identity)
	}
	if _, err := wechat.Exchange("test-code", parsed.Query().Get("state")); err == nil {
		t.Fatal("OAuth state was reusable")
	}
}
