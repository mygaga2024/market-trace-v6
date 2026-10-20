package domain

import "time"

type User struct {
	ID             string     `json:"id"`
	Username       string     `json:"username"`
	DisplayName    string     `json:"display_name"`
	Role           string     `json:"role"`
	AuthProvider   string     `json:"auth_provider"`
	Disabled       bool       `json:"disabled"`
	TradingEnabled bool       `json:"trading_enabled"`
	CreatedAt      time.Time  `json:"created_at"`
	LastLoginAt    *time.Time `json:"last_login_at,omitempty"`
}

type AuthStatus struct {
	Initialized   bool        `json:"initialized"`
	Authenticated bool        `json:"authenticated"`
	User          *User       `json:"user,omitempty"`
	Registration  bool        `json:"registration_enabled"`
	QRLogin       QRLoginInfo `json:"qr_login"`
}

type QRLoginInfo struct {
	Configured bool   `json:"configured"`
	Mode       string `json:"mode"`
	Name       string `json:"name"`
	Reason     string `json:"reason,omitempty"`
}
