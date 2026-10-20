package auth

import (
	"crypto/rand"
	"encoding/base64"
	"sync"
	"time"
)

type Session struct {
	Token     string
	UserID    string
	CreatedAt time.Time
	ExpiresAt time.Time
}

type SessionManager struct {
	mu       sync.Mutex
	sessions map[string]Session
	ttl      time.Duration
	now      func() time.Time
}

func NewSessionManager(ttl time.Duration) *SessionManager {
	if ttl <= 0 {
		ttl = 7 * 24 * time.Hour
	}
	return &SessionManager{
		sessions: make(map[string]Session),
		ttl:      ttl,
		now:      time.Now,
	}
}

func (m *SessionManager) Create(userID string) (Session, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return Session{}, err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	now := m.now()
	session := Session{
		Token:     token,
		UserID:    userID,
		CreatedAt: now,
		ExpiresAt: now.Add(m.ttl),
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.cleanupLocked(now)
	m.sessions[token] = session
	return session, nil
}

func (m *SessionManager) Get(token string) (Session, bool) {
	if token == "" {
		return Session{}, false
	}
	now := m.now()
	m.mu.Lock()
	defer m.mu.Unlock()
	session, ok := m.sessions[token]
	if !ok {
		return Session{}, false
	}
	if now.After(session.ExpiresAt) {
		delete(m.sessions, token)
		return Session{}, false
	}
	return session, true
}

func (m *SessionManager) Delete(token string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.sessions, token)
}

func (m *SessionManager) cleanupLocked(now time.Time) {
	for token, session := range m.sessions {
		if now.After(session.ExpiresAt) {
			delete(m.sessions, token)
		}
	}
}
