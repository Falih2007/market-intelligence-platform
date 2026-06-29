from fastapi import FastAPI
from fetch_data import fetch_ohlcv, save_to_db
from signals import read_from_db, calculate_rsi, generate_rsi_signals, save_signals_to_db
from explainer import explain_signal
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
def root():
    return {"message": "Market Intelligence Platform API"}

@app.get("/analyze/{ticker}")
def analyze(ticker: str):
    df_raw = fetch_ohlcv(ticker)
    save_to_db(df_raw, ticker)

    df = read_from_db(ticker)
    df = calculate_rsi(df)
    df = generate_rsi_signals(df)
    save_signals_to_db(df, ticker)

    # Only take 3 most recent signals to limit API calls
    signals = df[df["signal"].notna()].tail(3)
    results = []

    for date, row in signals.iterrows():
        explanation = explain_signal(ticker, row["signal"], row["close_price"], row["rsi"])
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