package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mygaga2024/market-trace-v6/internal/config"
	"github.com/mygaga2024/market-trace-v6/internal/market"
	"github.com/mygaga2024/market-trace-v6/internal/server"
	"github.com/mygaga2024/market-trace-v6/internal/store"
	"github.com/mygaga2024/market-trace-v6/internal/trading"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	cfg := config.Load()
	state, err := store.Open(cfg.DataFile)
	if err != nil {
		logger.Error("无法初始化持久化存储", "error", err)
		os.Exit(1)
	}
	provider := market.NewEastmoneyProvider(&http.Client{Timeout: 8 * time.Second})
	service := market.NewService(provider, state)
	tradingManager := trading.NewManager(state, service, service, trading.ManagerConfigFromEnv(), logger)
	app, err := server.New(cfg, state, service, tradingManager, logger)
	if err != nil {
		logger.Error("无法初始化 Web 服务", "error", err)
		os.Exit(1)
	}

	httpServer := &http.Server{
		Addr:              cfg.Address,
		Handler:           app,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      20 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	appCtx, appCancel := context.WithCancel(context.Background())
	defer appCancel()
	go tradingManager.StartCustodyLoop(appCtx)

	go func() {
		logger.Info("Market Trace Go 已启动", "address", cfg.Address, "data", cfg.DataFile, "api_token", cfg.APIToken != "", "registration", cfg.AllowRegistration)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP 服务异常退出", "error", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	appCancel()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpServer.Shutdown(ctx); err != nil {
		logger.Error("服务关闭失败", "error", err)
	}
	logger.Info("Market Trace Go 已停止")
}
