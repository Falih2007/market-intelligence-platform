from __future__ import annotations

from typing import Any

import yfinance as yf

from fetch_data import get_connection

INITIAL_CASH = 100000.00

def _get_current_price(ticker: str) -> float:
    try:
        price = yf.Ticker(ticker).fast_info.get("last_price")
        if price is not None and float(price) > 0:
            return float(price)
    except Exception:
        pass
    
    # Fallback: use recent history (works outside market hours)
    hist = yf.Ticker(ticker).history(period="5d")
    if hist.empty:
        raise ValueError(f"Could not fetch price for {ticker}")
    return float(hist["Close"].iloc[-1])

def _ensure_tables(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_cash (
            id TINYINT PRIMARY KEY,
            balance DOUBLE NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_portfolio (
            ticker VARCHAR(20) PRIMARY KEY,
            shares DOUBLE NOT NULL,
            avg_buy_price DOUBLE NOT NULL,
            opened_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            action VARCHAR(10) NOT NULL,
            shares DOUBLE NOT NULL,
            price DOUBLE NOT NULL,
            total_value DOUBLE NOT NULL,
            pnl DOUBLE NULL,
            executed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _ensure_cash_row(cursor) -> None:
    cursor.execute("SELECT balance FROM paper_cash WHERE id = 1")
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO paper_cash (id, balance) VALUES (1, %s)",
            (INITIAL_CASH,),
        )


def get_portfolio_state() -> dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        _ensure_tables(cursor)
        _ensure_cash_row(cursor)
        conn.commit()

        cursor.execute("SELECT balance FROM paper_cash WHERE id = 1")
        cash_row = cursor.fetchone()
        cash = float(cash_row["balance"])

        cursor.execute(
            """
            SELECT ticker, shares, avg_buy_price, opened_at
            FROM paper_portfolio
            ORDER BY opened_at
            """
        )
        raw_positions = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    positions = []
    total_market_value = 0.0
    for pos in raw_positions:
        current_price = _get_current_price(pos["ticker"])
        shares = float(pos["shares"])
        avg_buy_price = float(pos["avg_buy_price"])
        market_value = shares * current_price
        cost_basis = shares * avg_buy_price
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis != 0 else 0.0

        positions.append(
            {
                "ticker": pos["ticker"],
                "shares": shares,
                "avg_buy_price": avg_buy_price,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "opened_at": pos["opened_at"].isoformat(sep=" "),
            }
        )
        total_market_value += market_value

    total_equity = cash + total_market_value
    total_pnl = total_equity - INITIAL_CASH
    total_pnl_pct = (total_pnl / INITIAL_CASH) * 100

    return {
        "cash": cash,
        "positions": positions,
        "total_market_value": total_market_value,
        "total_equity": total_equity,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
    }


def execute_buy(ticker: str, shares: float) -> dict[str, Any]:
    if shares <= 0:
        raise ValueError("Shares must be greater than zero")

    ticker = ticker.upper()
    price = _get_current_price(ticker)
    total_cost = shares * price

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        _ensure_tables(cursor)
        _ensure_cash_row(cursor)

        cursor.execute("SELECT balance FROM paper_cash WHERE id = 1 FOR UPDATE")
        cash_row = cursor.fetchone()
        current_cash = float(cash_row["balance"])
        if current_cash < total_cost:
            raise ValueError("Insufficient funds")

        new_balance = current_cash - total_cost
        cursor.execute("UPDATE paper_cash SET balance = %s WHERE id = 1", (new_balance,))

        cursor.execute(
            "SELECT shares, avg_buy_price FROM paper_portfolio WHERE ticker = %s FOR UPDATE",
            (ticker,),
        )
        position_row = cursor.fetchone()
        if position_row:
            old_shares = float(position_row["shares"])
            old_avg = float(position_row["avg_buy_price"])
            new_shares = old_shares + shares
            new_avg_price = ((old_shares * old_avg) + total_cost) / new_shares
            cursor.execute(
                """
                UPDATE paper_portfolio
                SET shares = %s, avg_buy_price = %s
                WHERE ticker = %s
                """,
                (new_shares, new_avg_price, ticker),
            )
        else:
            cursor.execute(
                """
                INSERT INTO paper_portfolio (ticker, shares, avg_buy_price)
                VALUES (%s, %s, %s)
                """,
                (ticker, shares, price),
            )

        cursor.execute(
            """
            INSERT INTO paper_trades (ticker, action, shares, price, total_value, pnl)
            VALUES (%s, 'BUY', %s, %s, %s, NULL)
            """,
            (ticker, shares, price, total_cost),
        )

        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return {
        "success": True,
        "ticker": ticker,
        "shares": shares,
        "price": price,
        "total_cost": total_cost,
        "remaining_cash": new_balance,
    }


def execute_sell(ticker: str, shares: float) -> dict[str, Any]:
    if shares <= 0:
        raise ValueError("Shares must be greater than zero")

    ticker = ticker.upper()
    price = _get_current_price(ticker)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        _ensure_tables(cursor)
        _ensure_cash_row(cursor)

        cursor.execute(
            "SELECT shares, avg_buy_price FROM paper_portfolio WHERE ticker = %s FOR UPDATE",
            (ticker,),
        )
        position_row = cursor.fetchone()
        if position_row is None:
            raise ValueError("Position not found")

        current_shares = float(position_row["shares"])
        avg_buy_price = float(position_row["avg_buy_price"])
        if shares > current_shares:
            raise ValueError("Not enough shares to sell")

        proceeds = shares * price
        pnl = (price - avg_buy_price) * shares
        cost_basis = avg_buy_price * shares
        pnl_pct = (pnl / cost_basis * 100) if cost_basis != 0 else 0.0

        cursor.execute("SELECT balance FROM paper_cash WHERE id = 1 FOR UPDATE")
        cash_row = cursor.fetchone()
        current_cash = float(cash_row["balance"])
        new_balance = current_cash + proceeds
        cursor.execute("UPDATE paper_cash SET balance = %s WHERE id = 1", (new_balance,))

        remaining_shares = current_shares - shares
        if remaining_shares <= 0:
            cursor.execute("DELETE FROM paper_portfolio WHERE ticker = %s", (ticker,))
        else:
            cursor.execute(
                "UPDATE paper_portfolio SET shares = %s WHERE ticker = %s",
                (remaining_shares, ticker),
            )

        cursor.execute(
            """
            INSERT INTO paper_trades (ticker, action, shares, price, total_value, pnl)
            VALUES (%s, 'SELL', %s, %s, %s, %s)
            """,
            (ticker, shares, price, proceeds, pnl),
        )

        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return {
        "success": True,
        "ticker": ticker,
        "shares": shares,
        "price": price,
        "proceeds": proceeds,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def get_trade_history() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        _ensure_tables(cursor)
        _ensure_cash_row(cursor)
        conn.commit()

        cursor.execute(
            """
            SELECT id, ticker, action, shares, price, total_value, pnl, executed_at
            FROM paper_trades
            ORDER BY executed_at DESC
            """
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    history = []
    for row in rows:
        history.append(
            {
                "id": row["id"],
                "ticker": row["ticker"],
                "action": row["action"],
                "shares": float(row["shares"]),
                "price": float(row["price"]),
                "total_value": float(row["total_value"]),
                "pnl": float(row["pnl"]) if row["pnl"] is not None else None,
                "executed_at": row["executed_at"].isoformat(sep=" "),
            }
        )
    return history


def reset_portfolio() -> dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _ensure_tables(cursor)
        cursor.execute("DELETE FROM paper_portfolio")
        cursor.execute("DELETE FROM paper_trades")
        cursor.execute(
            """
            INSERT INTO paper_cash (id, balance)
            VALUES (1, %s)
            ON DUPLICATE KEY UPDATE balance = VALUES(balance)
            """,
            (INITIAL_CASH,),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return {"success": True, "message": "Portfolio reset to $100,000"}
