import yfinance as yf
import pandas as pd
import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "ghouse@1974",
    "database": "market_data"
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