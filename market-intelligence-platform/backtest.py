from __future__ import annotations

from typing import Any

import mysql.connector
import pandas as pd

from fetch_data import get_connection


def _fetch_ohlcv_for_backtest(ticker: str, period_days: int) -> pd.DataFrame:
    conn = get_connection()
    try:
        try:
            df = pd.read_sql(
                """
                SELECT date, open AS open_price, close AS close_price
                FROM ohlcv
                WHERE ticker = %s
                ORDER BY date DESC
                LIMIT %s
                """,
                conn,
                params=(ticker, period_days),
            )
        except mysql.connector.Error as err:
            # Support schemas that store prices as open_price/close_price.
            if err.errno != 1054:
                raise
            df = pd.read_sql(
                """
                SELECT date, open_price, close_price
                FROM ohlcv
                WHERE ticker = %s
                ORDER BY date DESC
                LIMIT %s
                """,
                conn,
                params=(ticker, period_days),
            )
    finally:
        conn.close()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    result = df.copy()
    delta = result["close_price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    result["rsi"] = 100 - (100 / (1 + rs))
    return result


def _generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["signal"] = None
    result.loc[result["rsi"] < 30, "signal"] = "BUY"
    result.loc[result["rsi"] > 70, "signal"] = "SELL"
    return result


def _generate_macd_signals(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    fast_ema = result["close_price"].ewm(span=12, adjust=False).mean()
    slow_ema = result["close_price"].ewm(span=26, adjust=False).mean()
    result["macd_line"] = fast_ema - slow_ema
    result["signal_line"] = result["macd_line"].ewm(span=9, adjust=False).mean()

    prev_macd = result["macd_line"].shift(1)
    prev_signal = result["signal_line"].shift(1)
    crossed_above = (prev_macd < prev_signal) & (result["macd_line"] > result["signal_line"])
    crossed_below = (prev_macd > prev_signal) & (result["macd_line"] < result["signal_line"])

    result["signal"] = None
    result.loc[crossed_above, "signal"] = "BUY"
    result.loc[crossed_below, "signal"] = "SELL"
    return result


def _generate_ma_crossover_signals(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["ma_fast"] = result["close_price"].rolling(window=20).mean()
    result["ma_slow"] = result["close_price"].rolling(window=50).mean()

    prev_fast = result["ma_fast"].shift(1)
    prev_slow = result["ma_slow"].shift(1)
    crossed_above = (prev_fast < prev_slow) & (result["ma_fast"] > result["ma_slow"])
    crossed_below = (prev_fast > prev_slow) & (result["ma_fast"] < result["ma_slow"])

    result["signal"] = None
    result.loc[crossed_above, "signal"] = "BUY"
    result.loc[crossed_below, "signal"] = "SELL"
    return result


def _simulate_long_only_trades(df: pd.DataFrame) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    open_position: dict[str, Any] | None = None

    for i in range(len(df) - 1):
        signal = df.at[i, "signal"]
        next_open = float(df.at[i + 1, "open_price"])
        next_date = pd.Timestamp(df.at[i + 1, "date"]).date().isoformat()

        if signal == "BUY" and open_position is None:
            open_position = {"entry_date": next_date, "entry_price": next_open}
            continue

        if signal == "SELL" and open_position is not None:
            entry_price = float(open_position["entry_price"])
            trade_return_pct = ((next_open - entry_price) / entry_price) * 100
            trades.append(
                {
                    "entry_date": open_position["entry_date"],
                    "entry_price": entry_price,
                    "exit_date": next_date,
                    "exit_price": next_open,
                    "return_pct": trade_return_pct,
                    "pnl_type": "WIN" if trade_return_pct > 0 else "LOSS",
                }
            )
            open_position = None

    return trades


def _build_metrics(trades: list[dict[str, Any]], message: str | None = None) -> dict[str, Any]:
    num_trades = len(trades)

    if num_trades == 0:
        return {
            "message": message or "No trades generated",
            "num_trades": 0,
            "trades": [],
        }

    if num_trades == 1:
        trade = trades[0]
        single_return = float(trade["return_pct"])
        is_win = trade["pnl_type"] == "WIN"

        return {
            "total_return": single_return,
            "win_rate": 100.0 if is_win else 0.0,
            "avg_return": single_return,
            "max_drawdown": 0.0 if is_win else abs(single_return),
            "sharpe_ratio": None,
            "num_trades": 1,
            "trades": trades,
        }

    returns = pd.Series([trade["return_pct"] / 100 for trade in trades], dtype="float64")
    equity_curve = (1 + returns).cumprod()
    rolling_peak = equity_curve.cummax()
    drawdown = (equity_curve / rolling_peak) - 1

    total_return = float((equity_curve.iloc[-1] - 1) * 100)
    win_rate = float((returns.gt(0).mean()) * 100)
    avg_return = float(returns.mean() * 100)
    max_drawdown = float(abs(drawdown.min()) * 100)

    returns_std = returns.std(ddof=1)
    sharpe_ratio = None
    if returns_std and returns_std > 0:
        sharpe_ratio = float((returns.mean() / returns_std) * (252**0.5))

    return {
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "num_trades": num_trades,
        "trades": trades,
    }


def run_backtest(ticker: str, strategy: str = "rsi", period_days: int = 90) -> dict[str, Any]:
    if period_days <= 0:
        return _build_metrics(trades=[], message="period_days must be greater than 0.")

    df = _fetch_ohlcv_for_backtest(ticker=ticker, period_days=period_days)
    if df.empty:
        return _build_metrics(trades=[], message=f"No OHLCV data found for ticker '{ticker}'.")

    strategy_key = strategy.lower()
    if strategy_key == "rsi":
        df = _calculate_rsi(df, period=14)
        df = _generate_signals(df)
    elif strategy_key == "macd":
        df = _generate_macd_signals(df)
    elif strategy_key == "ma_crossover":
        if len(df) < 100:
            raise ValueError("MA Crossover needs at least 100 days of data. Please select a longer period.")
        df = _generate_ma_crossover_signals(df)
    else:
        raise ValueError("Unknown strategy")

    trades = _simulate_long_only_trades(df)
    return _build_metrics(trades=trades)
