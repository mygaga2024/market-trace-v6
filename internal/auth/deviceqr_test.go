package auth

import (
	"errors"
	"testing"
	"time"
)

func TestDeviceQRApproveAndConsume(t *testing.T) {
	manager := NewDeviceQRManager(3 * time.Minute)
	now := time.Now()
	manager.now = func() time.Time { return now }
	code, err := manager.Create()
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	result, err := manager.Poll(code.ID, code.PollToken)
	if err != nil || result.Status != "pending" {
		t.Fatalf("pending Poll() = %+v, %v", result, err)
	}
	if err := manager.Approve(code.ApproveToken, "usr-1"); err != nil {
		t.Fatalf("Approve() error = %v", err)
	}
	result, err = manager.Poll(code.ID, code.PollToken)
	if err != nil || result.Status != "approved" || result.UserID != "usr-1" {
		t.Fatalf("approved Poll() = %+v, %v", result, err)
	}
	result, err = manager.Poll(code.ID, code.PollToken)
	if err != nil || result.Status != "consumed" {
		t.Fatalf("second Poll() = %+v, %v", result, err)
	}
}

func TestDeviceQRRejectsWrongPollToken(t *testing.T) {
	manager := NewDeviceQRManager(time.Minute)
	code, err := manager.Create()
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if _, err := manager.Poll(code.ID, "wrong"); !errors.Is(err, ErrQRUnauthorized) {
		t.Fatalf("Poll() error = %v, want ErrQRUnauthorized", err)
	}
}

func TestDeviceQRExpires(t *testing.T) {
	manager := NewDeviceQRManager(time.Minute)
	now := time.Now()
	manager.now = func() time.Time { return now }
	code, err := manager.Create()
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	manager.now = func() time.Time { return now.Add(2 * time.Minute) }
	result, err := manager.Poll(code.ID, code.PollToken)
	if err != nil || result.Status != "expired" {
		t.Fatalf("expired Poll() = %+v, %v", result, err)
	}
	if err := manager.Approve(code.ApproveToken, "usr-1"); !errors.Is(err, ErrQRExpired) {
		t.Fatalf("Approve() error = %v, want ErrQRExpired", err)
	}
}
