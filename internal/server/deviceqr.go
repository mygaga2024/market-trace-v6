package server

import (
	"bytes"
	"encoding/base64"
	"errors"
	"net/http"
	"net/url"
	"strings"

	qrcode "github.com/skip2/go-qrcode"

	"github.com/mygaga2024/market-trace-v6/internal/auth"
	webui "github.com/mygaga2024/market-trace-v6/web"
)

func (s *Server) qrStart(w http.ResponseWriter, r *http.Request) {
	key := "device-qr:" + clientIP(r)
	if !s.auth.loginLimiter.Allow(key) {
		writeError(w, http.StatusTooManyRequests, "扫码请求过于频繁，请稍后再试")
		return
	}
	code, err := s.auth.deviceQR.Create()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "生成扫码请求失败")
		return
	}
	scheme := "http"
	if s.config.SecureCookie || strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https") {
		scheme = "https"
	}
	approveURL := scheme + "://" + r.Host + "/qr/approve?t=" + url.QueryEscape(code.ApproveToken)
	image, err := qrcode.New(approveURL, qrcode.Medium)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "生成二维码失败")
		return
	}
	var png bytes.Buffer
	if err := image.Write(320, &png); err != nil {
		writeError(w, http.StatusInternalServerError, "生成二维码图片失败")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"mode":           "device",
		"request_id":     code.ID,
		"poll_token":     code.PollToken,
		"approve_url":    approveURL,
		"image_data_url": "data:image/png;base64," + base64.StdEncoding.EncodeToString(png.Bytes()),
		"expires_at":     code.ExpiresAt,
	})
}

func (s *Server) qrStatus(w http.ResponseWriter, r *http.Request) {
	requestID := strings.TrimSpace(r.URL.Query().Get("request_id"))
	pollToken := strings.TrimSpace(r.URL.Query().Get("poll_token"))
	if requestID == "" || pollToken == "" {
		writeError(w, http.StatusBadRequest, "缺少扫码请求参数")
		return
	}
	result, err := s.auth.deviceQR.Poll(requestID, pollToken)
	if errors.Is(err, auth.ErrQRNotFound) {
		writeError(w, http.StatusNotFound, "扫码请求不存在或已过期")
		return
	}
	if errors.Is(err, auth.ErrQRUnauthorized) {
		writeError(w, http.StatusUnauthorized, "扫码轮询凭证无效")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if result.Status != "approved" || result.UserID == "" {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":     result.Status,
			"expires_at": result.ExpiresAt,
		})
		return
	}
	record, ok := s.store.UserByID(result.UserID)
	if !ok || record.Disabled {
		writeError(w, http.StatusForbidden, "授权账户不存在或已停用")
		return
	}
	if err := s.auth.startSession(w, record.ID); err != nil {
		writeError(w, http.StatusInternalServerError, "创建登录会话失败")
		return
	}
	_ = s.store.MarkUserLogin(record.ID)
	writeJSON(w, http.StatusOK, map[string]any{
		"status":   "approved",
		"user":     record.Public(),
		"redirect": "/",
	})
}

func (s *Server) qrApprovePage(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.auth.currentUser(r); !ok {
		next := "/qr/approve?t=" + url.QueryEscape(r.URL.Query().Get("t"))
		http.Redirect(w, r, "/login?next="+url.QueryEscape(next), http.StatusSeeOther)
		return
	}
	raw, err := webui.QRApprove()
	if err != nil {
		http.Error(w, "页面资源不可用", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	_, _ = w.Write(raw)
}

func (s *Server) qrApprove(w http.ResponseWriter, r *http.Request) {
	user, ok := currentUserFromContext(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "请先登录")
		return
	}
	var body struct {
		Token string `json:"token"`
	}
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "请求体格式错误")
		return
	}
	err := s.auth.deviceQR.Approve(body.Token, user.ID)
	switch {
	case errors.Is(err, auth.ErrQRNotFound):
		writeError(w, http.StatusNotFound, "扫码请求不存在")
		return
	case errors.Is(err, auth.ErrQRExpired):
		writeError(w, http.StatusGone, "扫码请求已过期，请刷新二维码")
		return
	case errors.Is(err, auth.ErrQRConsumed):
		writeError(w, http.StatusConflict, "扫码请求已被使用")
		return
	case errors.Is(err, auth.ErrQRUnauthorized):
		writeError(w, http.StatusConflict, "扫码请求已由其他账户处理")
		return
	case err != nil:
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	s.store.RecordAudit("auth", "扫码授权登录", user.Username, "device-qr", "确认在另一台设备登录")
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "user": user})
}
