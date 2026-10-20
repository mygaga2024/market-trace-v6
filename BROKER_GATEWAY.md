# Official Broker Gateway Contract

Market Trace does not contain a broker login bypass or an unofficial trading API. Live orders are sent to a separately deployed gateway that uses the broker's official SDK or authorized order channel.

## Security requirements

- Use HTTPS. Plain HTTP is rejected unless `BROKER_GATEWAY_ALLOW_HTTP=true` is explicitly set for a trusted internal network.
- The gateway must enforce account permissions, market rules and broker-side risk controls independently.
- Never expose broker credentials to the browser or store them in this application.
- Gateway requests are signed with HMAC-SHA256 and should reject timestamps outside a short replay window.

## Authentication headers

Every request contains:

```text
X-MT6-Key: <BROKER_GATEWAY_KEY_ID>
X-MT6-Timestamp: <unix-seconds>
X-MT6-Signature: <hex HMAC-SHA256>
```

The signature input is:

```text
timestamp + "\n" + UPPERCASE_HTTP_METHOD + "\n" + path_with_query + "\n" + raw_body
```

Example:

```text
1700000000
POST
/v1/orders
{"account_id":"acct-1","order":{"symbol":"600519"}}
```

## GET /v1/account?account_id=...

Response:

```json
{
  "mode": "live",
  "broker": "Broker Name",
  "cash": 100000.00,
  "market_value": 25000.00,
  "total_equity": 125000.00,
  "day_pnl": 320.50,
  "positions": [
    {
      "symbol": "600519",
      "name": "贵州茅台",
      "quantity": 100,
      "available": 100,
      "avg_cost": 1300.00,
      "prev_close": 1320.00,
      "last_price": 1325.00,
      "market_value": 132500.00,
      "unrealized_pnl": 2500.00,
      "unrealized_pct": 1.92
    }
  ],
  "updated_at": "2026-10-20T11:00:00+08:00"
}
```

## POST /v1/orders

Request:

```json
{
  "account_id": "acct-1",
  "source": "manual",
  "actor": "admin",
  "order": {
    "client_order_id": "web-...",
    "symbol": "600519",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": 100,
    "limit_price": 1320.00,
    "reason": "manual order"
  }
}
```

Response is an `Order` object:

```json
{
  "id": "ord-...",
  "client_order_id": "web-...",
  "broker_order_id": "broker-123",
  "symbol": "600519",
  "name": "贵州茅台",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 100,
  "filled_quantity": 0,
  "limit_price": 1320.00,
  "avg_fill_price": 0,
  "status": "PENDING",
  "mode": "live",
  "source": "manual",
  "created_at": "2026-10-20T11:00:00+08:00",
  "updated_at": "2026-10-20T11:00:00+08:00"
}
```

Supported statuses: `SUBMITTED`, `PENDING`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REJECTED`.

## GET /v1/orders?account_id=...&limit=...

```json
{
  "items": [
    {
      "id": "ord-...",
      "status": "FILLED"
    }
  ]
}
```

## POST /v1/orders/{id}/cancel

Request:

```json
{
  "account_id": "acct-1",
  "actor": "admin"
}
```

The response must be the updated `Order` object.

## Enable live mode

```dotenv
TRADING_MODE=live
ALLOW_LIVE_TRADING=true
BROKER_GATEWAY_URL=https://your-gateway.example:9443
BROKER_GATEWAY_KEY_ID=key-id
BROKER_GATEWAY_SECRET=long-random-secret
BROKER_ACCOUNT_ID=acct-1
```

For live custody additionally set:

```dotenv
ALLOW_LIVE_CUSTODY=true
```

If any required value is missing, Market Trace stays in paper mode and reports why. It never reports a simulated fill as a live fill.
