package auth

import (
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
