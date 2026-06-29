import pandas as pd
import mysql.connector
from fetch_data import get_connection

def read_from_db(ticker: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        "SELECT date, close_price FROM ohlcv WHERE ticker = %s ORDER BY date",
        conn,
        params=(ticker,)
    )
    conn.close()
    df.set_index("date", inplace=True)
    return df

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["close_price"].diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))
    
    return df

def generate_rsi_signals(df: pd.DataFrame) -> pd.DataFrame:
    df["signal"] = None
    df.loc[df["rsi"] < 30, "signal"] = "BUY"   # oversold
    df.loc[df["rsi"] > 70, "signal"] = "SELL"  # overbought
    return df

def save_signals_to_db(df: pd.DataFrame, ticker: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INT AUTO_INCREMENT PRIMARY KEY,
            date DATETIME,
            ticker VARCHAR(10),
            close_price FLOAT,
            rsi FLOAT,
            signal_type VARCHAR(10)
        )
    """)

    # Clear old signals for this ticker first
    cursor.execute("DELETE FROM signals WHERE ticker = %s", (ticker,))

    for date, row in df[df["signal"].notna()].iterrows():
        cursor.execute("""
            INSERT INTO signals (date, ticker, close_price, rsi, signal_type)
            VALUES (%s, %s, %s, %s, %s)
        """, (date, ticker, row.close_price, row.rsi, row.signal))

    conn.commit()
    cursor.close()
    conn.close()

from explainer import explain_signal

def explain_all_signals(df: pd.DataFrame, ticker: str):
    signals = df[df["signal"].notna()]
    
    for date, row in signals.iterrows():
        print(f"\n--- {date.date()} | {row['signal']} | RSI: {row['rsi']:.1f} | Close: ${row['close_price']:.2f} ---")
        context = {
            "current_price": round(row["close_price"], 2),
            "rsi": round(row["rsi"], 2),
            "macd_line": None,
            "signal_line": None,
            "macd_histogram": None,
            "ma_20": None,
            "ma_50": None,
            "ma_200": None,
            "volume_today": None,
            "volume_avg_20d": None,
            "price_change_1d": None,
            "price_change_5d": None,
            "price_change_20d": None,
            "week_52_high": None,
            "week_52_low": None,
            "pct_from_52w_high": None,
            "pct_from_52w_low": None,
            "backtest_win_rate": None,
            "backtest_total_return": None,
            "backtest_num_trades": None,
        }
        explanation = explain_signal(ticker, row["signal"], context)
        print(explanation)

if __name__ == "__main__":
    if __name__ == "__main__":
        df = read_from_db("AAPL")
        df = calculate_rsi(df)
        df = generate_rsi_signals(df)
        save_signals_to_db(df, "AAPL")
        explain_all_signals(df, "AAPL")