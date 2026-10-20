package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Address      string
	DataFile     string
	APIToken     string
	SecureCookie bool
	Version      string
	Timeout      time.Duration
}

func Load() Config {
	port := strings.TrimSpace(os.Getenv("PORT"))
	if port == "" {
		port = "19377"
	}
	address := strings.TrimSpace(os.Getenv("MT6_ADDRESS"))
	if address == "" {
		address = "0.0.0.0:" + port
	}
	dataDir := strings.TrimSpace(os.Getenv("MT6_DATA_DIR"))
	if dataDir == "" {
		dataDir = "data/go"
	}
	apiToken := strings.TrimSpace(os.Getenv("API_TOKEN"))
	if strings.HasPrefix(apiToken, "your-") {
		apiToken = ""
	}
	secure := false
	if raw, err := strconv.ParseBool(strings.TrimSpace(os.Getenv("MT6_HTTPS"))); err == nil {
		secure = raw
	}
	timeout := 12 * time.Second
	if raw := strings.TrimSpace(os.Getenv("MT6_REQUEST_TIMEOUT")); raw != "" {
		if parsed, err := time.ParseDuration(raw); err == nil && parsed > 0 {
			timeout = parsed
		}
	}
	return Config{
		Address:      address,
		DataFile:     strings.TrimRight(dataDir, "/") + "/state.json",
		APIToken:     apiToken,
		SecureCookie: secure,
		Version:      "2.0.0",
		Timeout:      timeout,
	}
}
