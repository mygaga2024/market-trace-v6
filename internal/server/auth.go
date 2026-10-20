package server

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"net/http"
	"strings"
	"sync"
	"time"
)

const sessionCookie = "mt6_go_session"

type authManager struct {
	token        string
	secureCookie bool

	mu       sync.Mutex
	sessions map[string]time.Time
	now      func() time.Time
}

func newAuthManager(token string, secure bool) *authManager {
	return &authManager{
		token:        token,
		secureCookie: secure,
		sessions:     make(map[string]time.Time),
		now:          time.Now,
	}
}

func (a *authManager) enabled() bool {
	return a.token != ""
}

func (a *authManager) authenticated(r *http.Request) bool {
	if !a.enabled() {
		return true
	}
	header := strings.TrimSpace(r.Header.Get("Authorization"))
	if strings.HasPrefix(header, "Bearer ") {
		token := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
		if equalToken(token, a.token) {
			return true
		}
	}
	cookie, err := r.Cookie(sessionCookie)
	if err != nil || cookie.Value == "" {
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	expiry, ok := a.sessions[cookie.Value]
	if !ok || a.now().After(expiry) {
		delete(a.sessions, cookie.Value)
		return false
	}
	return true
}

func (a *authManager) login(token string) (string, bool) {
	if !a.enabled() || !equalToken(token, a.token) {
		return "", false
	}
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", false
	}
	session := hex.EncodeToString(raw)
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessions[session] = a.now().Add(24 * time.Hour)
	return session, true
}

func (a *authManager) setCookie(w http.ResponseWriter, session string) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    session,
		Path:     "/",
		HttpOnly: true,
		Secure:   a.secureCookie,
		SameSite: http.SameSiteStrictMode,
		MaxAge:   86400,
	})
}

func (a *authManager) clearCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		Secure:   a.secureCookie,
		SameSite: http.SameSiteStrictMode,
		MaxAge:   -1,
	})
}

func equalToken(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}
