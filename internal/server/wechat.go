package server

import (
	"net/http"
	"net/url"

	authpkg "github.com/mygaga2024/market-trace-v6/internal/auth"
)

func (s *Server) wechatStart(w http.ResponseWriter, r *http.Request) {
	if !s.auth.wechat.Configured() {
		writeError(w, http.StatusServiceUnavailable, s.auth.wechat.MissingReason())
		return
	}
	key := "wechat-login:" + clientIP(r)
	if !s.auth.loginLimiter.Allow(key) {
		writeError(w, http.StatusTooManyRequests, "微信登录请求过于频繁，请稍后再试")
		return
	}
	loginURL, err := s.auth.wechat.StartURL()
	if err != nil {
		writeError(w, http.StatusServiceUnavailable, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"configured": true,
		"provider":   "wechat",
		"url":        loginURL,
	})
}

func (s *Server) wechatCallback(w http.ResponseWriter, r *http.Request) {
	identity, err := s.auth.wechat.Exchange(r.URL.Query().Get("code"), r.URL.Query().Get("state"))
	if err != nil {
		http.Redirect(w, r, "/login?wechat_error="+url.QueryEscape(err.Error()), http.StatusSeeOther)
		return
	}
	record, ok := s.store.UserByProviderSubject(identity.Provider, identity.Subject)
	if !ok {
		if s.store.UserCount() > 0 && !s.auth.allowRegistration {
			http.Redirect(w, r, "/login?wechat_error="+url.QueryEscape("公开注册已关闭，微信账户尚未绑定"), http.StatusSeeOther)
			return
		}
		user, createErr := s.store.CreateUser(
			authpkg.WeChatUsername(identity.Subject),
			identity.Nickname,
			"",
			identity.Provider,
			identity.Subject,
		)
		if createErr != nil {
			http.Redirect(w, r, "/login?wechat_error="+url.QueryEscape("创建微信账户失败"), http.StatusSeeOther)
			return
		}
		record, _ = s.store.UserByID(user.ID)
	}
	if record.Disabled {
		http.Redirect(w, r, "/login?wechat_error="+url.QueryEscape("账户已停用"), http.StatusSeeOther)
		return
	}
	_ = s.store.MarkUserLogin(record.ID)
	if err := s.auth.startSession(w, record.ID); err != nil {
		http.Redirect(w, r, "/login?wechat_error="+url.QueryEscape("创建登录会话失败"), http.StatusSeeOther)
		return
	}
	http.Redirect(w, r, "/", http.StatusSeeOther)
}
