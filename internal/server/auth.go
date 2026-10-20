package server

import (
	"context"
	"crypto/subtle"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/auth"
	"github.com/mygaga2024/market-trace-v6/internal/config"
	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/store"
)

const sessionCookieName = "mt6_session"

type userContextKey struct{}

type authService struct {
	store             *store.Store
	sessions          *auth.SessionManager
	oauth             *auth.OAuthProvider
	loginLimiter      *auth.AttemptLimiter
	registerLimiter   *auth.AttemptLimiter
	apiToken          string
	secureCookie      bool
	allowRegistration bool
}

func newAuthService(state *store.Store, cfg config.Config) *authService {
	return &authService{
		store:             state,
		sessions:          auth.NewSessionManager(cfg.SessionTTL),
		oauth:             auth.NewOAuthProvider(auth.OAuthConfigFromEnv()),
		loginLimiter:      auth.NewAttemptLimiter(8, 10*time.Minute),
		registerLimiter:   auth.NewAttemptLimiter(5, 30*time.Minute),
		apiToken:          cfg.APIToken,
		secureCookie:      cfg.SecureCookie,
		allowRegistration: cfg.AllowRegistration,
	}
}

func (a *authService) currentUser(r *http.Request) (domain.User, bool) {
	if a.apiToken != "" {
		header := strings.TrimSpace(r.Header.Get("Authorization"))
		if strings.HasPrefix(header, "Bearer ") {
			token := strings.TrimSpace(strings.TrimPrefix(header, "Bearer "))
			if len(token) == len(a.apiToken) && subtle.ConstantTimeCompare([]byte(token), []byte(a.apiToken)) == 1 {
				return domain.User{
					ID:             "api-token",
					Username:       "api-token",
					DisplayName:    "API 客户端",
					Role:           "owner",
					TradingEnabled: true,
					AuthProvider:   "api-token",
				}, true
			}
		}
	}
	cookie, err := r.Cookie(sessionCookieName)
	if err != nil {
		return domain.User{}, false
	}
	session, ok := a.sessions.Get(cookie.Value)
	if !ok {
		return domain.User{}, false
	}
	record, ok := a.store.UserByID(session.UserID)
	if !ok || record.Disabled {
		a.sessions.Delete(cookie.Value)
		return domain.User{}, false
	}
	return record.Public(), true
}

func (a *authService) startSession(w http.ResponseWriter, userID string) error {
	session, err := a.sessions.Create(userID)
	if err != nil {
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookieName,
		Value:    session.Token,
		Path:     "/",
		HttpOnly: true,
		Secure:   a.secureCookie,
		SameSite: http.SameSiteStrictMode,
		MaxAge:   int(time.Until(session.ExpiresAt).Seconds()),
	})
	return nil
}

func (a *authService) endSession(w http.ResponseWriter, r *http.Request) {
	if cookie, err := r.Cookie(sessionCookieName); err == nil {
		a.sessions.Delete(cookie.Value)
	}
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookieName,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		Secure:   a.secureCookie,
		SameSite: http.SameSiteStrictMode,
		MaxAge:   -1,
	})
}

func (a *authService) status(r *http.Request) domain.AuthStatus {
	user, authenticated := a.currentUser(r)
	status := domain.AuthStatus{
		Initialized:   a.store.UserCount() > 0,
		Authenticated: authenticated,
		Registration:  a.allowRegistration || a.store.UserCount() == 0,
		QRLogin: domain.QRLoginInfo{
			Configured: a.oauth.Configured(),
			Name:       a.oauth.Name(),
			Reason:     a.oauth.MissingReason(),
		},
	}
	if authenticated {
		status.User = &user
	}
	return status
}

func withUser(r *http.Request, user domain.User) *http.Request {
	return r.WithContext(context.WithValue(r.Context(), userContextKey{}, user))
}

func currentUserFromContext(r *http.Request) (domain.User, bool) {
	user, ok := r.Context().Value(userContextKey{}).(domain.User)
	return user, ok
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}

func sameOriginRequest(r *http.Request) bool {
	switch r.Method {
	case http.MethodGet, http.MethodHead, http.MethodOptions:
		return true
	}
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" {
		origin = strings.TrimSpace(r.Header.Get("Referer"))
	}
	if origin == "" {
		return true
	}
	parsed, err := url.Parse(origin)
	if err != nil {
		return false
	}
	return strings.EqualFold(parsed.Host, r.Host)
}
