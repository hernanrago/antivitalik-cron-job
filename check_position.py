import hashlib
import hmac
import time
import urllib.parse
import requests
import os

API_KEY    = os.environ["BINGX_API_KEY"]
API_SECRET = os.environ["BINGX_API_SECRET"]
BASE_URL   = "https://open-api.bingx.com"

def get_signature(params: dict, secret: str) -> str:
    query_string = urllib.parse.urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def get_positions(symbol: str = "") -> dict:
    endpoint = "/openApi/swap/v2/user/positions"
    params = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    if symbol:
        params["symbol"] = symbol

    params["signature"] = get_signature(params, API_SECRET)

    headers = {"X-BX-APIKEY": API_KEY}
    response = requests.get(BASE_URL + endpoint, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

def format_position(pos: dict) -> str:
    side       = "LONG 🟢" if float(pos.get("positionAmt", 0)) > 0 else "SHORT 🔴"
    symbol     = pos.get("symbol", "N/A")
    size       = abs(float(pos.get("positionAmt", 0)))
    entry      = float(pos.get("avgPrice", 0))
    mark       = float(pos.get("markPrice", 0))
    pnl        = float(pos.get("unrealizedProfit", 0))
    leverage   = pos.get("leverage", "N/A")
    margin     = float(pos.get("initialMargin", 0))
    liq_price  = float(pos.get("liquidationPrice", 0))
    pnl_pct    = (pnl / margin * 100) if margin else 0
    pnl_icon   = "✅" if pnl >= 0 else "❌"

    return (
        f"{'='*50}\n"
        f"  Symbol    : {symbol}\n"
        f"  Side      : {side}\n"
        f"  Size      : {size}\n"
        f"  Leverage  : {leverage}x\n"
        f"  Entry     : {entry:.4f} USDT\n"
        f"  Mark      : {mark:.4f} USDT\n"
        f"  Liq Price : {liq_price:.4f} USDT\n"
        f"  PnL       : {pnl_icon} {pnl:+.4f} USDT ({pnl_pct:+.2f}%)\n"
        f"  Margin    : {margin:.4f} USDT\n"
        f"{'='*50}"
    )

def main():
    print(f"\n🕐 BingX Position Check — {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")

    data = get_positions()

    if data.get("code") != 0:
        print(f"❌ API Error {data.get('code')}: {data.get('msg')}")
        return

    positions = data.get("data", [])

    # Filtrar posiciones activas (size != 0)
    active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    if not active:
        print("📭 No hay posiciones abiertas.")
        return

    print(f"📊 Posiciones abiertas: {len(active)}\n")
    for pos in active:
        print(format_position(pos))

    # Resumen PnL total
    total_pnl = sum(float(p.get("unrealizedProfit", 0)) for p in active)
    pnl_icon  = "✅" if total_pnl >= 0 else "❌"
    print(f"\n{pnl_icon} PnL Total No Realizado: {total_pnl:+.4f} USDT\n")

if __name__ == "__main__":
    main()
