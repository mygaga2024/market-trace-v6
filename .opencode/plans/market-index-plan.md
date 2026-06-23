# 大盘板块指数 + 持仓自动刷新 — 实施计划

## 目标
1. 新增大盘板块指数卡片（上证/深证/创业板/科创50/沪深300）
2. 持仓列表增加自动刷新倒计时指示

## 后端改动

### 1. 新建 `api/market_index.py`
- 路由: `GET /api/market/index`
- 从 Redis `market:macro` 读取缓存的指数数据
- 返回格式: `{ indices: [{code, name, close, 涨跌幅, volume, amount, date}], timestamp, source }`

### 2. 修改 `main.py`
- 在路由注册区添加 `from api.market_index import router as market_index_router`
- 添加 `app.include_router(market_index_router)`

## 前端改动

### 3. 修改 `templates/dashboard.html`
- 在 "风险偏好指数 RAI" 卡片后新增 "大盘指数" 卡片

### 4. 修改 `static/js/dashboard.js`
- `load()` 函数中添加 `fetchAuth('/api/market/index')` 调用
- 新增 `_renderMarketIndexCard(indices)` 渲染函数
- 新增自动刷新倒计时指示

### 5. 修改 `static/css/dashboard.css`
- 大盘指数卡片样式

### 6. 修改 `dev_server.py`
- 添加 `GET:/api/market/index` mock handler

## 验证
- pytest tests/ -v
- NAS 部署后 curl /api/market/index 验证返回值
- webfetch 抓页面验证大盘指数卡片渲染
- 验证持仓列表倒计时指示显示
