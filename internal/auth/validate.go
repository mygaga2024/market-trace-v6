package auth

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
)

var ErrInvalidUsername = errors.New("用户名需为 3-64 位，可使用字母、数字、点、下划线、@ 或短横线")

func NormalizeUsername(username string) (string, error) {
	username = strings.ToLower(strings.TrimSpace(username))
	if len(username) < 3 || len(username) > 64 {
		return "", ErrInvalidUsername
	}
	for _, r := range username {
		valid := (r >= 'a' && r <= 'z') ||
			(r >= '0' && r <= '9') ||
			r == '_' || r == '.' || r == '@' || r == '-'
		if !valid {
			return "", ErrInvalidUsername
		}
	}
	return username, nil
}

func SafeExternalUsername(provider, subject string) string {
	candidate, err := NormalizeUsername(subject)
	if err == nil {
		return candidate
	}
	sum := sha256.Sum256([]byte(provider + "\x00" + subject))
	return "qr_" + hex.EncodeToString(sum[:8])
}
