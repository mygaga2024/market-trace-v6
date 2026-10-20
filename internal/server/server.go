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

	authpkg "github.com/mygaga2024/market-trace-v6/internal/auth"
	"github.com/mygaga2024/market-trace-v6/internal/config"
	"github.com/mygaga2024/market-trace-v6/internal/domain"
	"github.com/mygaga2024/market-trace-v6/internal/market"
	"github.com/mygaga2024/market-trace-v6/internal/store"
	"github.com/mygaga2024/market-trace-v6/internal/trading"
	webui "github.com/mygaga2024/market-trace-v6/web"
)

type Server struct {
	config  config.Config
	store   *store.Store
	market  *market.Service
	trading *trading.Manager
	auth    *authService
	logger  *slog.Logger
	started time.Time
	handler http.Handler
}

func New(cfg config.Config, state *store.Store, marketService *market.Service, tradingManager *trading.Manager, logger *slog.Logger) (*Server, error) {
	if logger == nil {
		logger = slog.Default()
	}
	s := &Server{
		config:  cfg,
		store:   state,
		market:  marketService,
		trading: tradingManager,
		auth:    newAuthService(state, cfg),
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
	mux.HandleFunc("GET /register", s.registerPage)
	mux.HandleFunc("POST /logout", s.logout)
	mux.HandleFunc("POST /api/v1/auth/login", s.apiLogin)
	mux.HandleFunc("POST /api/v1/auth/register", s.apiRegister)
	mux.HandleFunc("POST /api/v1/auth/logout", s.apiLogout)
	mux.HandleFunc("POST /api/v1/auth/password", s.apiChangePassword)
	mux.HandleFunc("GET /api/v1/auth/status", s.authStatus)
	mux.HandleFunc("GET /api/v1/auth/qr/start", s.qrStart)
	mux.HandleFunc("GET /api/v1/auth/qr/status", s.qrStatus)
	mux.HandleFunc("POST /api/v1/auth/qr/approve", s.qrApprove)
	mux.HandleFunc("GET /qr/approve", s.qrApprovePage)
	mux.HandleFunc("GET /api/v1/auth/wechat/start", s.wechatStart)
	mux.HandleFunc("GET /auth/wechat/callback", s.wechatCallback)
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
	mux.HandleFunc("GET /api/v1/users", s.users)
	mux.HandleFunc("POST /api/v1/users/{id}/trading", s.updateUserTrading)
	mux.HandleFunc("GET /api/v1/trading/account", s.tradingAccount)
	mux.HandleFunc("GET /api/v1/trading/orders", s.tradingOrders)
	mux.HandleFunc("POST /api/v1/trading/orders", s.placeOrder)
	mux.HandleFunc("POST /api/v1/trading/orders/{id}/cancel", s.cancelOrder)
	mux.HandleFunc("GET /api/v1/custody", s.custody)
	mux.HandleFunc("PUT /api/v1/custody", s.updateCustody)
	mux.HandleFunc("POST /api/v1/custody/run", s.runCustody)

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
	if _, ok := s.auth.currentUser(r); !ok {
		if s.store.UserCount() == 0 {
			http.Redirect(w, r, "/register", http.StatusSeeOther)
		} else {
			http.Redirect(w, r, "/login", http.StatusSeeOther)
		}
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
	if _, ok := s.auth.currentUser(r); ok {
		http.Redirect(w, r, safeNextPath(r.URL.Query().Get("next")), http.StatusSeeOther)
		return
	}
	if s.store.UserCount() == 0 {
		http.Redirect(w, r, "/register", http.StatusSeeOther)
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

func (s *Server) registerPage(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.auth.currentUser(r); ok {
		http.Redirect(w, r, safeNextPath(r.URL.Query().Get("next")), http.StatusSeeOther)
		return
	}
	if s.store.UserCount() > 0 && !s.auth.allowRegistration {
		http.Redirect(w, r, "/login", http.StatusSeeOther)
		return
	}
	raw, err := webui.Register()
	if err != nil {
		http.Error(w, "页面资源不可用", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(raw)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	s.auth.endSession(w, r)
	http.Redirect(w, r, "/login", http.StatusSeeOther)
}

func (s *Server) apiRegister(w http.ResponseWriter, r *http.Request) {
	if s.store.UserCount() > 0 && !s.auth.allowRegistration {
		writeError(w, http.StatusForbidden, "公开注册已关闭")
		return
	}
	key := "register:" + clientIP(r)
	if !s.auth.registerLimiter.Allow(key) {
		writeError(w, http.StatusTooManyRequests, "注册尝试过于频繁，请稍后再试")
		return
	}
	var body struct {
		Username    string `json:"username"`
		DisplayName string `json:"display_name"`
		Password    string `json:"password"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	username, err := authpkg.NormalizeUsername(body.Username)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	hash, err := authpkg.HashPassword(body.Password)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	user, err := s.store.CreateUser(username, body.DisplayName, hash, "local", "")
	if errors.Is(err, store.ErrExists) {
		writeError(w, http.StatusConflict, "该用户名已注册")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "注册失败")
		return
	}
	if err := s.auth.startSession(w, user.ID); err != nil {
		writeError(w, http.StatusInternalServerError, "创建登录会话失败")
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"ok": true, "user": user, "redirect": "/"})
}

func (s *Server) apiLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	username, err := authpkg.NormalizeUsername(body.Username)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "用户名或密码错误")
		return
	}
	key := "login:" + clientIP(r) + ":" + username
	if !s.auth.loginLimiter.Allow(key) {
		writeError(w, http.StatusTooManyRequests, "登录尝试过于频繁，请 10 分钟后再试")
		return
	}
	record, ok := s.store.UserByUsername(username)
	if !ok || record.Disabled || record.PasswordHash == "" || !authpkg.VerifyPassword(record.PasswordHash, body.Password) {
		writeError(w, http.StatusUnauthorized, "用户名或密码错误")
		return
	}
	s.auth.loginLimiter.Reset(key)
	_ = s.store.MarkUserLogin(record.ID)
	if err := s.auth.startSession(w, record.ID); err != nil {
		writeError(w, http.StatusInternalServerError, "创建登录会话失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "user": record.Public(), "redirect": "/"})
}

func (s *Server) apiLogout(w http.ResponseWriter, r *http.Request) {
	s.auth.endSession(w, r)
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) apiChangePassword(w http.ResponseWriter, r *http.Request) {
	user, ok := currentUserFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "请先登录")
		return
	}
	var body struct {
		CurrentPassword string `json:"current_password"`
		NewPassword     string `json:"new_password"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	record, ok := s.store.UserByID(user.ID)
	if !ok {
		writeError(w, http.StatusUnauthorized, "账户不存在")
		return
	}
	if record.PasswordHash != "" && !authpkg.VerifyPassword(record.PasswordHash, body.CurrentPassword) {
		writeError(w, http.StatusUnauthorized, "当前密码错误")
		return
	}
	hash, err := authpkg.HashPassword(body.NewPassword)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := s.store.UpdatePassword(user.ID, hash); err != nil {
		writeError(w, http.StatusInternalServerError, "保存新密码失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) authStatus(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, s.auth.status(r))
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	payload := s.market.Health(ctx)
	payload["uptime_seconds"] = int64(time.Since(s.started).Seconds())
	writeJSON(w, http.StatusOK, payload)
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
	payload.Account = s.trading.Account(ctx)
	if orders, err := s.trading.Orders(ctx, 50); err == nil {
		payload.Orders = orders
	} else {
		payload.Orders = []domain.Order{}
	}
	payload.Custody = s.trading.CustodySettings()
	payload.Trading = s.trading.Status()
	payload.Version = s.config.Version
	if user, ok := currentUserFromContext(r); ok {
		payload.CurrentUser = &user
	}
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

func (s *Server) users(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireOwner(w, r); !ok {
		return
	}
	items := s.store.Users()
	writeJSON(w, http.StatusOK, map[string]any{"count": len(items), "items": items})
}

func (s *Server) updateUserTrading(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.requireOwner(w, r); !ok {
		return
	}
	var body struct {
		Enabled bool `json:"enabled"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	if err := s.store.SetUserTradingEnabled(r.PathValue("id"), body.Enabled); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "用户不存在")
			return
		}
		writeError(w, http.StatusInternalServerError, "更新交易权限失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (s *Server) tradingAccount(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	writeJSON(w, http.StatusOK, s.trading.Account(ctx))
}

func (s *Server) tradingOrders(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	orders, err := s.trading.Orders(ctx, 100)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"count": len(orders), "items": orders})
}

func (s *Server) placeOrder(w http.ResponseWriter, r *http.Request) {
	user, ok := s.requireTrader(w, r)
	if !ok {
		return
	}
	var request domain.OrderRequest
	if err := decodeJSON(r, &request); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	order, err := s.trading.PlaceOrder(ctx, request, "manual", user.Username)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, order)
}

func (s *Server) cancelOrder(w http.ResponseWriter, r *http.Request) {
	user, ok := s.requireTrader(w, r)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.config.Timeout)
	defer cancel()
	order, err := s.trading.CancelOrder(ctx, r.PathValue("id"), user.Username)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, order)
}

func (s *Server) custody(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"settings": s.trading.CustodySettings(),
		"status":   s.trading.Status(),
	})
}

func (s *Server) updateCustody(w http.ResponseWriter, r *http.Request) {
	user, ok := s.requireOwner(w, r)
	if !ok {
		return
	}
	var body struct {
		domain.CustodySettings
		Confirmation string `json:"confirmation"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	settings, err := s.trading.UpdateCustody(body.CustodySettings, body.Confirmation, user.Username)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, settings)
}

func (s *Server) runCustody(w http.ResponseWriter, r *http.Request) {
	user, ok := s.requireOwner(w, r)
	if !ok {
		return
	}
	var body struct {
		Force bool `json:"force"`
	}
	if r.ContentLength != 0 {
		if err := decodeJSON(r, &body); err != nil {
			writeError(w, http.StatusBadRequest, "请求体格式错误")
			return
		}
	}
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	orders, err := s.trading.RunCustodyOnce(ctx, user.Username, body.Force)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"count": len(orders), "items": orders})
}

func (s *Server) requireTrader(w http.ResponseWriter, r *http.Request) (domain.User, bool) {
	user, ok := currentUserFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "请先登录")
		return domain.User{}, false
	}
	if !user.TradingEnabled && user.Role != "owner" {
		writeError(w, http.StatusForbidden, "当前账户未开启交易权限")
		return domain.User{}, false
	}
	return user, true
}

func (s *Server) requireOwner(w http.ResponseWriter, r *http.Request) (domain.User, bool) {
	user, ok := s.requireTrader(w, r)
	if !ok {
		return domain.User{}, false
	}
	if user.Role != "owner" {
		writeError(w, http.StatusForbidden, "该操作仅限管理员")
		return domain.User{}, false
	}
	return user, true
}

func (s *Server) withAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !sameOriginRequest(r) {
			writeError(w, http.StatusForbidden, "跨站请求已拒绝")
			return
		}
		if publicPath(r.URL.Path) {
			next.ServeHTTP(w, r)
			return
		}
		user, ok := s.auth.currentUser(r)
		if ok {
			next.ServeHTTP(w, withUser(r, user))
			return
		}
		if strings.HasPrefix(r.URL.Path, "/api/") {
			writeJSON(w, http.StatusUnauthorized, map[string]any{
				"error":          "请先登录",
				"setup_required": s.store.UserCount() == 0,
			})
			return
		}
		if s.store.UserCount() == 0 {
			http.Redirect(w, r, "/register", http.StatusSeeOther)
		} else {
			http.Redirect(w, r, "/login", http.StatusSeeOther)
		}
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
	return path == "/login" || path == "/register" || path == "/logout" || path == "/health" ||
		path == "/favicon.svg" || path == "/qr/approve" || path == "/auth/wechat/callback" ||
		path == "/api/v1/auth/status" || path == "/api/v1/auth/login" ||
		path == "/api/v1/auth/register" || path == "/api/v1/auth/qr/start" ||
		path == "/api/v1/auth/qr/status" || path == "/api/v1/auth/wechat/start" ||
		strings.HasPrefix(path, "/assets/")
}

func safeNextPath(value string) string {
	if value == "" || value[0] != '/' || strings.HasPrefix(value, "//") {
		return "/"
	}
	return value
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
