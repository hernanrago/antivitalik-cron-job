import hashlib
import hmac
import time
import urllib.parse
import requests
import os

API_KEY        = os.environ["BINGX_API_KEY"]
API_SECRET     = os.environ["BINGX_API_SECRET"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
BASE_URL       = "https://open-api.bingx.com"
EMAIL_TO       = "hernan.rago.1982@gmail.com"


# ── BingX ──────────────────────────────────────────────────────────────────────

def get_sign(secret: str, params_str: str) -> str:
    """BingX requiere HMAC-SHA256 sobre el query string SIN ordenar."""
    return hmac.new(
        secret.encode("utf-8"),
        params_str.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

def parse_params(params: dict) -> str:
    """Convierte dict a query string (sin ordenar, tal como lo requiere BingX)."""
    return "&".join(f"{k}={v}" for k, v in params.items())

def get_positions(symbol: str = "") -> dict:
    endpoint = "/openApi/swap/v2/user/positions"
    params = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    if symbol:
        params["symbol"] = symbol

    params_str = parse_params(params)
    signature  = get_sign(API_SECRET, params_str)

    # La firma va al final de la URL como parámetro separado
    url     = f"{BASE_URL}{endpoint}?{params_str}&signature={signature}"
    headers = {"X-BX-APIKEY": API_KEY}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


# ── Formateo ───────────────────────────────────────────────────────────────────

def format_position_text(pos: dict) -> str:
    side      = "LONG 🟢" if float(pos.get("positionAmt", 0)) > 0 else "SHORT 🔴"
    symbol    = pos.get("symbol", "N/A")
    size      = abs(float(pos.get("positionAmt", 0)))
    entry     = float(pos.get("avgPrice", 0))
    mark      = float(pos.get("markPrice", 0))
    pnl       = float(pos.get("unrealizedProfit", 0))
    leverage  = pos.get("leverage", "N/A")
    margin    = float(pos.get("initialMargin", 0))
    liq_price = float(pos.get("liquidationPrice", 0))
    pnl_pct   = (pnl / margin * 100) if margin else 0
    pnl_icon  = "✅" if pnl >= 0 else "❌"

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

def format_position_html(pos: dict) -> str:
    side      = "LONG 🟢" if float(pos.get("positionAmt", 0)) > 0 else "SHORT 🔴"
    symbol    = pos.get("symbol", "N/A")
    size      = abs(float(pos.get("positionAmt", 0)))
    entry     = float(pos.get("avgPrice", 0))
    mark      = float(pos.get("markPrice", 0))
    pnl       = float(pos.get("unrealizedProfit", 0))
    leverage  = pos.get("leverage", "N/A")
    margin    = float(pos.get("initialMargin", 0))
    liq_price = float(pos.get("liquidationPrice", 0))
    pnl_pct   = (pnl / margin * 100) if margin else 0
    pnl_color = "#16a34a" if pnl >= 0 else "#dc2626"
    pnl_icon  = "✅" if pnl >= 0 else "❌"

    return f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px;font-family:monospace;font-size:14px;">
      <thead>
        <tr style="background:#1e293b;color:#f1f5f9;">
          <th colspan="2" style="padding:10px 14px;text-align:left;">{symbol} — {side}</th>
        </tr>
      </thead>
      <tbody>
        <tr style="background:#f8fafc;"><td style="padding:6px 14px;color:#64748b;">Size</td><td style="padding:6px 14px;">{size} @ {leverage}x</td></tr>
        <tr><td style="padding:6px 14px;color:#64748b;">Entry Price</td><td style="padding:6px 14px;">{entry:.4f} USDT</td></tr>
        <tr style="background:#f8fafc;"><td style="padding:6px 14px;color:#64748b;">Mark Price</td><td style="padding:6px 14px;">{mark:.4f} USDT</td></tr>
        <tr><td style="padding:6px 14px;color:#64748b;">Liq. Price</td><td style="padding:6px 14px;">{liq_price:.4f} USDT</td></tr>
        <tr style="background:#f8fafc;"><td style="padding:6px 14px;color:#64748b;">Margin</td><td style="padding:6px 14px;">{margin:.4f} USDT</td></tr>
        <tr><td style="padding:6px 14px;color:#64748b;">Unrealized PnL</td>
            <td style="padding:6px 14px;font-weight:bold;color:{pnl_color};">{pnl_icon} {pnl:+.4f} USDT ({pnl_pct:+.2f}%)</td></tr>
      </tbody>
    </table>
    """

def build_email_html(active: list, total_pnl: float, timestamp: str) -> str:
    positions_html = "".join(format_position_html(p) for p in active)
    total_color = "#16a34a" if total_pnl >= 0 else "#dc2626"
    total_icon  = "✅" if total_pnl >= 0 else "❌"

    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;background:#ffffff;">
      <h2 style="margin:0 0 4px;color:#0f172a;">📊 BingX — Reporte de Posiciones</h2>
      <p style="margin:0 0 24px;color:#64748b;font-size:13px;">🕐 {timestamp}</p>

      {positions_html}

      <div style="background:#0f172a;color:#f1f5f9;padding:14px 18px;border-radius:8px;margin-top:8px;">
        <span style="font-size:14px;">PnL Total No Realizado</span>
        <span style="float:right;font-weight:bold;color:{total_color};font-size:16px;">
          {total_icon} {total_pnl:+.4f} USDT
        </span>
      </div>

      <p style="margin-top:24px;color:#94a3b8;font-size:11px;text-align:center;">
        BingX Position Monitor · GitHub Actions
      </p>
    </div>
    """


# ── Resend ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, html: str) -> None:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "BingX Monitor <onboarding@resend.dev>",
            "to": [EMAIL_TO],
            "subject": subject,
            "html": html,
        },
        timeout=10,
    )
    response.raise_for_status()
    print(f"📧 Email enviado → {EMAIL_TO}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    print(f"\n🕐 BingX Position Check — {timestamp}\n")

    symbol = os.environ.get("BINGX_SYMBOL", "").strip()
    if symbol:
        print(f"🔍 Filtrando por símbolo: {symbol}\n")

    data = get_positions(symbol)

    if data.get("code") != 0:
        print(f"❌ API Error {data.get('code')}: {data.get('msg')}")
        return

    positions = data.get("data", [])
    active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    if not active:
        print("📭 No hay posiciones abiertas.")
        return

    # Log en consola
    print(f"📊 Posiciones abiertas: {len(active)}\n")
    for pos in active:
        print(format_position_text(pos))

    total_pnl = sum(float(p.get("unrealizedProfit", 0)) for p in active)
    pnl_icon  = "✅" if total_pnl >= 0 else "❌"
    print(f"\n{pnl_icon} PnL Total No Realizado: {total_pnl:+.4f} USDT\n")

    # Enviar email
    subject = f"{pnl_icon} BingX | {len(active)} posición(es) | PnL: {total_pnl:+.4f} USDT"
    html    = build_email_html(active, total_pnl, timestamp)
    send_email(subject, html)


if __name__ == "__main__":
    main()
