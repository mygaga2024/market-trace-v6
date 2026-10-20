package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/config"
	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/market"
	"github.com/mygaga2024/market-trace-v6/internal/store"
	webui "github.com/mygaga2024/market-trace-v6/web"
)

type Server struct {
	config  config.Config
	store   *store.Store
	market  *market.Service
	auth    *authManager
	logger  *slog.Logger
	started time.Time
	handler http.Handler
}

func New(cfg config.Config, state *store.Store, marketService *market.Service, logger *slog.Logger) (*Server, error) {
	if logger == nil {
		logger = slog.Default()
	}
	s := &Server{
		config:  cfg,
		store:   state,
		market:  marketService,
		auth:    newAuthManager(cfg.APIToken, cfg.SecureCookie),
		logger:  logger,
		started: time.Now(),
	}
	if err := s.routes(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.handler.ServeHTTP(w, r)
}

func (s *Server) routes() error {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", s.index)
	mux.HandleFunc("GET /login", s.loginPage)
	mux.HandleFunc("POST /login", s.login)
	mux.HandleFunc("POST /logout", s.logout)
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /favicon.svg", s.favicon)

	mux.HandleFunc("GET /api/v1/dashboard", s.dashboard)
	mux.HandleFunc("GET /api/v1/stocks", s.stocks)
	mux.HandleFunc("POST /api/v1/stocks", s.addStock)
	mux.HandleFunc("DELETE /api/v1/stocks/{symbol}", s.deleteStock)
	mux.HandleFunc("POST /api/v1/analyze", s.analyze)
	mux.HandleFunc("GET /api/v1/decisions", s.decisions)
	mux.HandleFunc("GET /api/v1/audit", s.audit)
	mux.HandleFunc("GET /api/v1/settings", s.settings)
	mux.HandleFunc("PUT /api/v1/settings", s.updateSettings)
	mux.HandleFunc("POST /api/v1/strategies/{key}/toggle", s.toggleStrategy)

	assets, err := webui.Assets()
	if err != nil {
		return err
	}
	fileServer := http.FileServer(http.FS(assets))
	mux.Handle("GET /assets/", http.StripPrefix("/assets/", fileServer))

	s.handler = s.securityHeaders(s.withAuth(mux))
	return nil
}

func (s *Server) index(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	raw, err := webui.Index()
	if err != nil {
		http.Error(w, "页面资源不可用", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(raw)
}

func (s *Server) loginPage(w http.ResponseWriter, r *http.Request) {
	if !s.auth.enabled() {
		http.Redirect(w, r, "/", http.StatusSeeOther)
		return
	}
	raw, err := webui.Login()
	if err != nil {
		http.Error(w, "页面资源不可用", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(raw)
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	if !s.auth.enabled() {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "redirect": "/"})
		return
	}
	var token string
	contentType := r.Header.Get("Content-Type")
	if strings.Contains(contentType, "application/json") {
		var body struct {
			Token string `json:"token"`
		}
		if err := decodeJSON(r, &body); err != nil {
			writeError(w, http.StatusBadRequest, "请求体格式错误")
			return
		}
		token = body.Token
	} else {
		token = r.FormValue("token")
	}
	session, ok := s.auth.login(token)
	if !ok {
		writeError(w, http.StatusUnauthorized, "访问令牌无效")
		return
	}
	s.auth.setCookie(w, session)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "redirect": "/"})
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	s.auth.clearCookie(w)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	payload := s.market.Health(ctx)
	payload["uptime_seconds"] = int64(time.Since(s.started).Seconds())
	status := http.StatusOK
	if payload["status"] != "ok" {
		status = http.StatusServiceUnavailable
	}
	writeJSON(w, status, payload)
}

func (s *Server) favicon(w http.ResponseWriter, r *http.Request) {
	const icon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#14999a"/><path d="M17 24h30v23H17zM25 24v-6h14v6M17 34h30" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`
	w.Header().Set("Content-Type", "image/svg+xml")
	w.Header().Set("Cache-Control", "public, max-age=86400")
	_, _ = io.WriteString(w, icon)
}

func (s *Server) dashboard(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	payload := s.market.Dashboard(ctx)
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) stocks(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	dashboard := s.market.Dashboard(ctx)
	writeJSON(w, http.StatusOK, map[string]any{
		"count": len(dashboard.Stocks),
		"items": dashboard.Stocks,
	})
}

func (s *Server) addStock(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Symbol string `json:"symbol"`
		Name   string `json:"name"`
		Notes  string `json:"notes"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	item, err := s.store.AddStock(body.Symbol, body.Name, body.Notes)
	if errors.Is(err, store.ErrExists) {
		writeError(w, http.StatusConflict, "该股票已在自选名单中")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, item)
}

func (s *Server) deleteStock(w http.ResponseWriter, r *http.Request) {
	symbol := r.PathValue("symbol")
	err := s.store.RemoveStock(symbol)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "股票不在自选名单中")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "移除自选失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"symbol": symbol, "removed": true})
}

func (s *Server) analyze(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Symbol string `json:"symbol"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	analysis, err := s.market.Analyze(ctx, body.Symbol)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, analysis)
}

func (s *Server) decisions(w http.ResponseWriter, r *http.Request) {
	items := s.store.Decisions()
	writeJSON(w, http.StatusOK, map[string]any{"count": len(items), "items": items})
}

func (s *Server) audit(w http.ResponseWriter, r *http.Request) {
	items := s.store.Audits(100)
	writeJSON(w, http.StatusOK, map[string]any{"count": len(items), "items": items})
}

func (s *Server) settings(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.store.Settings())
}

func (s *Server) updateSettings(w http.ResponseWriter, r *http.Request) {
	var settings domain.RiskSettings
	if err := decodeJSON(r, &settings); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	updated, err := s.store.UpdateSettings(settings)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

func (s *Server) toggleStrategy(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Enabled bool `json:"enabled"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	err := s.store.ToggleStrategy(r.PathValue("key"), body.Enabled)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "策略不存在")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "策略状态保存失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) withAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.auth.enabled() || publicPath(r.URL.Path) || s.auth.authenticated(r) {
			next.ServeHTTP(w, r)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/api/") {
			writeError(w, http.StatusUnauthorized, "请先登录")
			return
		}
		http.Redirect(w, r, "/login", http.StatusSeeOther)
	})
}

func (s *Server) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "same-origin")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
		if strings.HasPrefix(r.URL.Path, "/api/") {
			w.Header().Set("Cache-Control", "no-store")
		}
		next.ServeHTTP(w, r)
	})
}

func publicPath(path string) bool {
	return path == "/" || path == "/login" || path == "/logout" || path == "/health" ||
		path == "/favicon.svg" || strings.HasPrefix(path, "/assets/")
}

func decodeJSON(r *http.Request, target any) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("请求体只能包含一个 JSON 对象")
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]any{"error": message})
}
