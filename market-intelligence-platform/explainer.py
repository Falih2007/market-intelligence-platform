import anthropic
import re
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are a professional quantitative analyst. Analyze the provided technical indicators 
and give a concise, insightful 3-4 sentence signal explanation. Be specific about which 
indicators are aligned or conflicting. Mention risk factors. Do not give financial advice 
- frame as analysis only.

Structure your response as exactly 3 short paragraphs separated by newlines:
1. Indicator alignment (what's confirming the signal)
2. Conflicting signals or risks
3. One-sentence summary verdict

Keep the total response under 120 words. Do not include any title or label like
'Analysis' or 'Summary' at the start."""


def _format_value(value):
    if value is None:
        return "N/A"
    return value


def explain_signal(ticker: str, signal_type: str, context: dict) -> str:
    prompt = f"""Signal Overview:
- Ticker: {ticker}
- Signal Type: {signal_type}

Technical Indicators:
- Current Price: {_format_value(context.get("current_price"))}
- RSI: {_format_value(context.get("rsi"))}
- MACD Line: {_format_value(context.get("macd_line"))}
- Signal Line: {_format_value(context.get("signal_line"))}
- MACD Histogram: {_format_value(context.get("macd_histogram"))}
- MA 20: {_format_value(context.get("ma_20"))}
- MA 50: {_format_value(context.get("ma_50"))}
- MA 200: {_format_value(context.get("ma_200"))}

Volume:
- Volume Today: {_format_value(context.get("volume_today"))}
- Avg Volume (20d): {_format_value(context.get("volume_avg_20d"))}

Price Change (%):
- 1D: {_format_value(context.get("price_change_1d"))}
- 5D: {_format_value(context.get("price_change_5d"))}
- 20D: {_format_value(context.get("price_change_20d"))}

52-Week Range:
- 52W High: {_format_value(context.get("week_52_high"))}
- 52W Low: {_format_value(context.get("week_52_low"))}
- % from 52W High: {_format_value(context.get("pct_from_52w_high"))}
- % from 52W Low: {_format_value(context.get("pct_from_52w_low"))}

Backtest Context:
- Backtest Win Rate: {_format_value(context.get("backtest_win_rate"))}
- Backtest Total Return: {_format_value(context.get("backtest_total_return"))}
- Backtest Number of Trades: {_format_value(context.get("backtest_num_trades"))}

Please provide a concise 3-4 sentence analysis-only explanation."""

    message = client.messages.create(
        system=SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    explanation = message.content[0].text
    explanation = re.sub(r'^[A-Z]+ (Buy|Sell|BUY|SELL) Signal Analysis\s*', '', explanation)
    return explanation

if __name__ == "__main__":
    # Test with a sample signal
    explanation = explain_signal(
        ticker="AAPL",
        signal_type="BUY",
        context={
            "current_price": 275.15,
            "rsi": 28.4,
            "macd_line": -0.7,
            "signal_line": -0.9,
            "macd_histogram": 0.2,
            "ma_20": 279.2,
            "ma_50": 282.8,
            "ma_200": 250.3,
            "volume_today": 87500000,
            "volume_avg_20d": 73000000,
            "price_change_1d": -1.3,
            "price_change_5d": -3.1,
            "price_change_20d": 4.8,
            "week_52_high": 290.5,
            "week_52_low": 164.1,
            "pct_from_52w_high": -5.3,
            "pct_from_52w_low": 67.6,
            "backtest_win_rate": 54.2,
            "backtest_total_return": 18.7,
            "backtest_num_trades": 12,
        },
    )
    print(repr(explanation))
