package auth

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"sync"
	"time"
)

var (
	ErrQRNotFound     = errors.New("扫码请求不存在")
	ErrQRExpired      = errors.New("扫码请求已过期")
	ErrQRConsumed     = errors.New("扫码请求已被使用")
	ErrQRUnauthorized = errors.New("扫码授权凭证无效")
)

type DeviceQRCode struct {
	ID           string
	PollToken    string
	ApproveToken string
	ExpiresAt    time.Time
}

type DeviceQRResult struct {
	Status    string
	UserID    string
	ExpiresAt time.Time
}

type deviceQRRequest struct {
	ID           string
	PollToken    string
	ApproveToken string
	CreatedAt    time.Time
	ExpiresAt    time.Time
	ApprovedBy   string
	Status       string
	Consumed     bool
}

type DeviceQRManager struct {
	mu       sync.Mutex
	requests map[string]*deviceQRRequest
	ttl      time.Duration
	now      func() time.Time
}

func NewDeviceQRManager(ttl time.Duration) *DeviceQRManager {
	if ttl <= 0 {
		ttl = 3 * time.Minute
	}
	return &DeviceQRManager{
		requests: make(map[string]*deviceQRRequest),
		ttl:      ttl,
		now:      time.Now,
	}
}

func (m *DeviceQRManager) Create() (DeviceQRCode, error) {
	id, err := randomURLToken(16)
	if err != nil {
		return DeviceQRCode{}, err
	}
	pollToken, err := randomURLToken(32)
	if err != nil {
		return DeviceQRCode{}, err
	}
	approveToken, err := randomURLToken(32)
	if err != nil {
		return DeviceQRCode{}, err
	}
	now := m.now()
	request := &deviceQRRequest{
		ID:           id,
		PollToken:    pollToken,
		ApproveToken: approveToken,
		CreatedAt:    now,
		ExpiresAt:    now.Add(m.ttl),
		Status:       "pending",
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.cleanupLocked(now)
	m.requests[id] = request
	m.requests[approveToken] = request
	return DeviceQRCode{
		ID:           id,
		PollToken:    pollToken,
		ApproveToken: approveToken,
		ExpiresAt:    request.ExpiresAt,
	}, nil
}

func (m *DeviceQRManager) Approve(approveToken, userID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	request, ok := m.requests[approveToken]
	if !ok {
		return ErrQRNotFound
	}
	now := m.now()
	if now.After(request.ExpiresAt) {
		request.Status = "expired"
		return ErrQRExpired
	}
	if request.Consumed {
		return ErrQRConsumed
	}
	if request.Status == "approved" {
		if request.ApprovedBy == userID {
			return nil
		}
		return ErrQRUnauthorized
	}
	request.Status = "approved"
	request.ApprovedBy = userID
	return nil
}

func (m *DeviceQRManager) Poll(id, pollToken string) (DeviceQRResult, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	request, ok := m.requests[id]
	if !ok {
		return DeviceQRResult{}, ErrQRNotFound
	}
	if subtle.ConstantTimeCompare([]byte(request.PollToken), []byte(pollToken)) != 1 {
		return DeviceQRResult{}, ErrQRUnauthorized
	}
	now := m.now()
	if now.After(request.ExpiresAt) {
		request.Status = "expired"
	}
	result := DeviceQRResult{
		Status:    request.Status,
		ExpiresAt: request.ExpiresAt,
	}
	if request.Status != "approved" || request.Consumed {
		if request.Consumed {
			result.Status = "consumed"
		}
		return result, nil
	}
	request.Consumed = true
	result.UserID = request.ApprovedBy
	return result, nil
}

func (m *DeviceQRManager) cleanupLocked(now time.Time) {
	for key, request := range m.requests {
		if now.After(request.ExpiresAt.Add(10 * time.Minute)) {
			delete(m.requests, key)
		}
	}
}

func randomURLToken(size int) (string, error) {
	raw := make([]byte, size)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}
