import os
import yfinance as yf
import pandas as pd
import mysql.connector

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "market_data")
}

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def setup_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            id INT AUTO_INCREMENT PRIMARY KEY,
            date DATETIME,
            ticker VARCHAR(10),
            open_price FLOAT,
            high_price FLOAT,
            low_price FLOAT,
            close_price FLOAT,
            volume BIGINT
        )
    """)
    cursor.execute('''
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
        trades_json TEXT  
    ''')
    conn.commit()
    cursor.close()
    conn.close()

def fetch_ohlcv(ticker: str, period: str = "6mo") -> pd.DataFrame:
    stock = yf.Ticker(ticker)
    df = stock.history(period=period)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df

def save_to_db(df: pd.DataFrame, ticker: str):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Clear old data for this ticker first
    cursor.execute("DELETE FROM ohlcv WHERE ticker = %s", (ticker,))
    
    for date, row in df.iterrows():
        cursor.execute("""
            INSERT INTO ohlcv (date, ticker, open_price, high_price, low_price, close_price, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (date, ticker, row.Open, row.High, row.Low, row.Close, row.Volume))
    
    conn.commit()
    cursor.close()
    conn.close()

def read_from_db(ticker: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        "SELECT * FROM ohlcv WHERE ticker = %s ORDER BY date",
        conn,
        params=(ticker,)
    )
    conn.close()
    return df

if __name__ == "__main__":
    setup_table()
    
    df = fetch_ohlcv("AAPL")
    save_to_db(df, "AAPL")
    
    # Read back from DB to confirm
    result = read_from_db("AAPL")
    print(result.tail(10))