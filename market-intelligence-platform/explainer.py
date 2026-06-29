import anthropic
import json
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

def explain_signal(ticker: str, signal_type: str, close_price: float, rsi: float) -> str:
    context = {
        "ticker": ticker,
        "signal_type": signal_type,
        "close_price": close_price,
        "rsi_value": round(rsi, 2)
    }

    prompt = f"""You are a financial analyst assistant. Given the following trading signal data, 
write a concise 2-3 sentence explanation of what this signal means and why it may be significant.
Be factual and based only on the data provided. Do not give direct investment advice.

Signal data:
{json.dumps(context, indent=2)}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return message.content[0].text

if __name__ == "__main__":
    # Test with a sample signal
    explanation = explain_signal(
        ticker="AAPL",
        signal_type="BUY",
        close_price=275.15,
        rsi=28.4
    )
    print(repr(explanation))
