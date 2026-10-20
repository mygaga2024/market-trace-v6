FROM golang:1.24-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
COPY cmd ./cmd
COPY internal ./internal
COPY web ./web

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/mt6 ./cmd/mt6

FROM alpine:3.21

RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S -g 1000 appuser \
    && adduser -S -D -H -u 1000 -G appuser appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

WORKDIR /app
COPY --from=builder /out/mt6 /usr/local/bin/mt6

ENV PORT=19377 \
    MT6_DATA_DIR=/app/data \
    TZ=Asia/Shanghai

EXPOSE 19377

USER appuser

HEALTHCHECK --interval=30s --timeout=8s --retries=3 --start-period=10s \
    CMD wget -qO- http://127.0.0.1:19377/health >/dev/null || exit 1

CMD ["mt6"]
