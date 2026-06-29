# Market Intelligence Platform

A lightweight full-stack market analysis app that:

- fetches historical stock data (OHLCV) from Yahoo Finance
- stores price and signal data in MySQL
- calculates RSI (Relative Strength Index)
- generates simple RSI-based BUY/SELL signals
- asks Claude (Anthropic API) to produce short human-readable signal explanations
- serves results through a FastAPI backend and an HTML + Chart.js frontend

## What this program does

When you enter a ticker (for example `AAPL`) in the UI:

1. The frontend calls `GET /analyze/{ticker}`.
2. The backend downloads recent price history with `yfinance`.
3. Data is saved into MySQL table `ohlcv`.
4. RSI is computed from close prices.
5. Signals are generated:
   - `BUY` when RSI < 30 (oversold)
   - `SELL` when RSI > 70 (overbought)
6. Signals are stored in MySQL table `signals`.
7. For the most recent signals, the app calls Anthropic to generate short explanations.
8. The frontend displays:
   - signal cards with explanation text
   - price chart
   - RSI chart

## Project structure

`market-intelligence-platform/`

- `main.py` - FastAPI app and API routes
- `fetch_data.py` - Yahoo Finance fetch + MySQL OHLCV storage
- `signals.py` - RSI calculation, signal generation, signal persistence
- `explainer.py` - Anthropic-powered signal explanations
- `index.html` - frontend UI (ticker search, charts, signal list)

## API endpoints

- `GET /` - health/message endpoint
- `GET /analyze/{ticker}` - fetch, compute, store, explain, return latest signals
- `GET /prices/{ticker}` - return historical close + RSI data for charting

## Requirements

- Python 3.10+
- MySQL server running locally
- Anthropic API key

Python packages used by the code:

- `fastapi`
- `uvicorn`
- `yfinance`
- `pandas`
- `mysql-connector-python`
- `anthropic`
- `python-dotenv`

## Environment variables

Create a `.env` file in `market-intelligence-platform\market-intelligence-platform\`:

```env
ANTHROPIC_API_KEY=your_key_here
```

## Database setup

The code currently uses these MySQL settings in `fetch_data.py`:

- host: `localhost`
- user: `root`
- database: `market_data`

Make sure:

1. MySQL is running
2. database `market_data` exists
3. credentials in `fetch_data.py` are valid for your machine

## Run locally

From repo root:

```powershell
cd market-intelligence-platform
python -m venv venv
venv\Scripts\activate
pip install fastapi uvicorn yfinance pandas mysql-connector-python anthropic python-dotenv
uvicorn main:app --reload
```

Then open `index.html` in your browser and use the ticker input.

## Notes

- This is an educational/demo signal app, not financial advice.
- Current strategy is RSI-only (simple threshold rules).
- CORS is open (`allow_origins=["*"]`) for local development convenience.