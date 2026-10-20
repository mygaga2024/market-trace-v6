package auth

import (
	"sync"
	"time"
)

type attemptBucket struct {
	Count   int
	ResetAt time.Time
}

type AttemptLimiter struct {
	mu      sync.Mutex
	buckets map[string]attemptBucket
	limit   int
	window  time.Duration
	now     func() time.Time
}

func NewAttemptLimiter(limit int, window time.Duration) *AttemptLimiter {
	return &AttemptLimiter{
		buckets: make(map[string]attemptBucket),
		limit:   limit,
		window:  window,
		now:     time.Now,
	}
}

func (l *AttemptLimiter) Allow(key string) bool {
	now := l.now()
	l.mu.Lock()
	defer l.mu.Unlock()
	bucket, ok := l.buckets[key]
	if !ok || now.After(bucket.ResetAt) {
		l.buckets[key] = attemptBucket{Count: 1, ResetAt: now.Add(l.window)}
		return true
	}
	if bucket.Count >= l.limit {
		return false
	}
	bucket.Count++
	l.buckets[key] = bucket
	return true
}

func (l *AttemptLimiter) Reset(key string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.buckets, key)
}
