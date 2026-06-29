import json

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fetch_data import fetch_ohlcv, get_connection, save_to_db
from signals import read_from_db, calculate_rsi, generate_rsi_signals, save_signals_to_db
from explainer import explain_signal
from backtest import run_backtest
from paper_trading import (
    execute_buy,
    execute_sell,
    get_portfolio_state,
    get_trade_history,
    reset_portfolio,
)
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _round_or_none(value, decimals: int = 2):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, decimals)


def _int_or_none(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return int(round(number))


def _pct_change(close_series: pd.Series, lookback_days: int):
    if len(close_series) <= lookback_days:
        return None
    previous_price = close_series.iloc[-(lookback_days + 1)]
    current_price = close_series.iloc[-1]
    if pd.isna(previous_price) or pd.isna(current_price) or previous_price == 0:
        return None
    return ((current_price - previous_price) / previous_price) * 100


class TradeRequest(BaseModel):
    ticker: str
    shares: float



@app.get("/")
def root():
    return {"message": "Market Intelligence Platform API"}

@app.get("/analyze/{ticker}")
def analyze(ticker: str):
    df_raw = fetch_ohlcv(ticker)
    save_to_db(df_raw, ticker)

    analysis_df = df_raw.copy()
    analysis_df.index = pd.to_datetime(analysis_df.index)
    if getattr(analysis_df.index, "tz", None) is not None:
        analysis_df.index = analysis_df.index.tz_localize(None)

    close = analysis_df["Close"]
    volume = analysis_df["Volume"]
    fast_ema = close.ewm(span=12, adjust=False).mean()
    slow_ema = close.ewm(span=26, adjust=False).mean()
    analysis_df["macd_line"] = fast_ema - slow_ema
    analysis_df["signal_line"] = analysis_df["macd_line"].ewm(span=9, adjust=False).mean()
    analysis_df["macd_histogram"] = analysis_df["macd_line"] - analysis_df["signal_line"]
    analysis_df["ma_20"] = close.rolling(window=20).mean()
    analysis_df["ma_50"] = close.rolling(window=50).mean()
    analysis_df["ma_200"] = close.rolling(window=200).mean()
    analysis_df["volume_avg_20d"] = volume.rolling(window=20).mean()

    backtest_win_rate = None
    backtest_total_return = None
    backtest_num_trades = None
    try:
        backtest_result = run_backtest(ticker=ticker, strategy="rsi", period_days=365)
        backtest_win_rate = backtest_result.get("win_rate")
        backtest_total_return = backtest_result.get("total_return")
        backtest_num_trades = backtest_result.get("num_trades")
    except Exception:
        backtest_win_rate = None
        backtest_total_return = None
        backtest_num_trades = None

    df = read_from_db(ticker)
    df = calculate_rsi(df)
    df = generate_rsi_signals(df)
    save_signals_to_db(df, ticker)

    # Only take 3 most recent signals to limit API calls
    signals = df[df["signal"].notna()].tail(3)
    results = []

    for date, row in signals.iterrows():
        signal_date = pd.to_datetime(date)
        if signal_date.tzinfo is not None:
            signal_date = signal_date.tz_localize(None)

        signal_slice = analysis_df[analysis_df.index <= signal_date]
        if signal_slice.empty:
            signal_slice = analysis_df[analysis_df.index.date <= signal_date.date()]

        slice_close = signal_slice["Close"] if not signal_slice.empty else pd.Series(dtype="float64")
        slice_volume = signal_slice["Volume"] if not signal_slice.empty else pd.Series(dtype="float64")
        last_row = signal_slice.iloc[-1] if not signal_slice.empty else None

        current_price = last_row["Close"] if last_row is not None else None
        week_52_high = (
            slice_close.rolling(window=252).max().iloc[-1]
            if not slice_close.empty
            else None
        )
        week_52_low = (
            slice_close.rolling(window=252).min().iloc[-1]
            if not slice_close.empty
            else None
        )

        pct_from_52w_high = None
        pct_from_52w_low = None
        if current_price is not None and week_52_high is not None and not pd.isna(week_52_high) and week_52_high != 0:
            pct_from_52w_high = ((current_price - week_52_high) / week_52_high) * 100
        if current_price is not None and week_52_low is not None and not pd.isna(week_52_low) and week_52_low != 0:
            pct_from_52w_low = ((current_price - week_52_low) / week_52_low) * 100

        context = {
            "current_price": _round_or_none(current_price),
            "rsi": _round_or_none(row["rsi"]),
            "macd_line": _round_or_none(last_row["macd_line"] if last_row is not None else None),
            "signal_line": _round_or_none(last_row["signal_line"] if last_row is not None else None),
            "macd_histogram": _round_or_none(last_row["macd_histogram"] if last_row is not None else None),
            "ma_20": _round_or_none(last_row["ma_20"] if last_row is not None else None),
            "ma_50": _round_or_none(last_row["ma_50"] if last_row is not None else None),
            "ma_200": _round_or_none(last_row["ma_200"] if last_row is not None else None),
            "volume_today": _int_or_none(slice_volume.iloc[-1] if not slice_volume.empty else None),
            "volume_avg_20d": _int_or_none(last_row["volume_avg_20d"] if last_row is not None else None),
            "price_change_1d": _round_or_none(_pct_change(slice_close, 1)),
            "price_change_5d": _round_or_none(_pct_change(slice_close, 5)),
            "price_change_20d": _round_or_none(_pct_change(slice_close, 20)),
            "week_52_high": _round_or_none(week_52_high),
            "week_52_low": _round_or_none(week_52_low),
            "pct_from_52w_high": _round_or_none(pct_from_52w_high),
            "pct_from_52w_low": _round_or_none(pct_from_52w_low),
            "backtest_win_rate": _round_or_none(backtest_win_rate),
            "backtest_total_return": _round_or_none(backtest_total_return),
            "backtest_num_trades": _int_or_none(backtest_num_trades),
        }
        explanation = explain_signal(ticker, row["signal"], context)
        results.append({
            "date": str(date.date()),
            "signal": row["signal"],
            "close_price": round(row["close_price"], 2),
            "rsi": round(row["rsi"], 2),
            "explanation": explanation
        })

    return {"ticker": ticker, "signals": results}

@app.get("/prices/{ticker}")
def prices(ticker: str):
    df = read_from_db(ticker)
    df = calculate_rsi(df)
    df = df.dropna(subset=["rsi"])
    
    result = []
    for date, row in df.iterrows():
        result.append({
            "date": str(date.date()),
            "close_price": round(row["close_price"], 2),
            "rsi": round(row["rsi"], 2)
        })
    return result


def save_backtest_result(ticker: str, strategy: str, period_days: int, metrics_dict: dict):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ticker VARCHAR(10),
            strategy VARCHAR(50),
            run_date DATETIME,
            period_days INT,
            total_return FLOAT,
            win_rate FLOAT,
            avg_return FLOAT,
            max_drawdown FLOAT,
            sharpe_ratio FLOAT,
            num_trades INT,
            trades_json JSON
        )
    """)

    cursor.execute("""
        INSERT INTO backtest_results (
            ticker, strategy, run_date, period_days,
            total_return, win_rate, avg_return, max_drawdown, sharpe_ratio,
            num_trades, trades_json
        )
        VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        ticker,
        strategy,
        period_days,
        metrics_dict.get("total_return"),
        metrics_dict.get("win_rate"),
        metrics_dict.get("avg_return"),
        metrics_dict.get("max_drawdown"),
        metrics_dict.get("sharpe_ratio"),
        metrics_dict.get("num_trades"),
        json.dumps(metrics_dict.get("trades", [])),
    ))

    conn.commit()
    cursor.close()
    conn.close()


@app.get("/backtest/{ticker}")
def backtest(ticker: str, strategy: str = "rsi", period: int = 90):
    try:
        backtest_result = run_backtest(ticker=ticker, strategy=strategy, period_days=period)
    except ValueError as exc:
        return {"error": str(exc)}

    save_backtest_result(
        ticker=ticker,
        strategy=strategy,
        period_days=period,
        metrics_dict=backtest_result,
    )

    trades = backtest_result.get("trades", [])
    metrics = {k: v for k, v in backtest_result.items() if k != "trades"}

    return {
        "ticker": ticker,
        "strategy": strategy,
        "period_days": period,
        "metrics": metrics,
        "trades": trades,
    }


@app.get("/compare/{ticker}")
def compare(ticker: str, period: int = 365):
    strategy_specs = [
        ("rsi", "RSI"),
        ("macd", "MACD"),
        ("ma_crossover", "MA Crossover"),
    ]
    comparison = []

    for strategy_key, strategy_label in strategy_specs:
        try:
            result = run_backtest(ticker=ticker, strategy=strategy_key, period_days=period)
            comparison.append(
                {
                    "strategy": strategy_label,
                    "total_return": result.get("total_return"),
                    "win_rate": result.get("win_rate"),
                    "sharpe_ratio": result.get("sharpe_ratio"),
                    "num_trades": result.get("num_trades"),
                }
            )
        except Exception as exc:
            comparison.append(
                {
                    "strategy": strategy_label,
                    "error": str(exc),
                }
            )

    return {
        "ticker": ticker,
        "period_days": period,
        "comparison": comparison,
    }


@app.get("/paper/portfolio")
def paper_portfolio():
    try:
        return get_portfolio_state()
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.post("/paper/buy")
def paper_buy(request: TradeRequest):
    try:
        return execute_buy(ticker=request.ticker, shares=request.shares)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.post("/paper/sell")
def paper_sell(request: TradeRequest):
    try:
        return execute_sell(ticker=request.ticker, shares=request.shares)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/paper/history")
def paper_history():
    try:
        return get_trade_history()
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.post("/paper/reset")
def paper_reset():
    try:
        return reset_portfolio()
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})