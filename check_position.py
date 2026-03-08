import hashlib
import hmac
import math
import time
import requests
import os

API_KEY        = os.environ["BINGX_API_KEY"]
API_SECRET     = os.environ["BINGX_API_SECRET"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
BASE_URL       = "https://open-api.bingx.com"
EMAIL_TO       = "hernan.rago.1982@gmail.com"

CAPITAL          = float(os.environ["CAPITAL"])
BULLET_SIZE      = CAPITAL / 30
DRY_RUN          = os.environ.get("DRY_RUN", "false").lower() == "true"
TARGET_PAIRS     = ["ADA-USDT", "ETH-USDT"]
SYMBOL_PRECISION = {"ADA-USDT": 0, "ETH-USDT": 3}


# ── BingX helpers ──────────────────────────────────────────────────────────────

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

    url     = f"{BASE_URL}{endpoint}?{params_str}&signature={signature}"
    headers = {"X-BX-APIKEY": API_KEY}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


# ── Resend ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, html: str) -> None:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "BingX DCA <onboarding@resend.dev>",
            "to": [EMAIL_TO],
            "subject": subject,
            "html": html,
        },
        timeout=10,
    )
    response.raise_for_status()
    print(f"Email enviado → {EMAIL_TO}")


# ── DCA logic ──────────────────────────────────────────────────────────────────

def get_position_for_symbol(symbol: str) -> dict | None:
    data = get_positions(symbol)
    if data.get("code") != 0:
        raise RuntimeError(f"API Error {data.get('code')}: {data.get('msg')}")
    positions = data.get("data", [])
    for pos in positions:
        if float(pos.get("positionAmt", 0)) != 0:
            return pos
    return None

def determine_action(roi: float) -> tuple[int, int]:
    """Retorna (bullets_to_position, bullets_to_margin)."""
    if roi < -60:
        return (0, 6)
    if roi < -40:
        return (3, 3)
    if roi < -15:
        return (6, 0)
    if roi < -10:
        return (5, 0)
    if roi < -5:
        return (4, 0)
    if roi <= 0:
        return (3, 0)
    if roi <= 5:
        return (2, 0)
    return (1, 0)

def calculate_quantity(bullets_usdt: float, mark_price: float, symbol: str) -> float:
    raw = bullets_usdt / mark_price
    precision = SYMBOL_PRECISION[symbol]
    return math.floor(raw * 10**precision) / 10**precision

def place_limit_order(symbol: str, position_side: str, quantity: float, price: float) -> dict:
    side = "BUY" if position_side == "LONG" else "SELL"
    if DRY_RUN:
        print(f"[DRY RUN] place_limit_order: {symbol} {side}/{position_side} qty={quantity} price={price}")
        return {"code": 0, "dry_run": True}

    endpoint = "/openApi/swap/v2/trade/order"
    params = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": "LIMIT",
        "quantity": quantity,
        "price": price,
    }
    params_str = parse_params(params)
    signature  = get_sign(API_SECRET, params_str)
    url        = f"{BASE_URL}{endpoint}?{params_str}&signature={signature}"
    headers    = {"X-BX-APIKEY": API_KEY}

    response = requests.post(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Order error {data.get('code')}: {data.get('msg')}")
    return data

def add_margin(symbol: str, position_side: str, amount_usdt: float) -> dict:
    if DRY_RUN:
        print(f"[DRY RUN] add_margin: {symbol} {position_side} amount={amount_usdt:.2f} USDT")
        return {"code": 0, "dry_run": True}

    endpoint = "/openApi/swap/v2/trade/positionMargin"
    params = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
        "symbol": symbol,
        "amount": amount_usdt,
        "type": 1,
        "positionSide": position_side,
    }
    params_str = parse_params(params)
    signature  = get_sign(API_SECRET, params_str)
    url        = f"{BASE_URL}{endpoint}?{params_str}&signature={signature}"
    headers    = {"X-BX-APIKEY": API_KEY}

    response = requests.post(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

def process_pair(symbol: str) -> dict:
    try:
        pos = get_position_for_symbol(symbol)
        if pos is None:
            return {"symbol": symbol, "has_position": False}

        unrealized_profit = float(pos.get("unrealizedProfit", 0))
        initial_margin    = float(pos.get("initialMargin", 0))
        mark_price        = float(pos.get("markPrice", 0))
        avg_price         = float(pos.get("avgPrice", 0))
        position_amt      = float(pos.get("positionAmt", 0))
        leverage          = pos.get("leverage", "N/A")
        liquidation_price = float(pos.get("liquidationPrice", 0))

        roi = (unrealized_profit / initial_margin * 100) if initial_margin != 0 else 0
        position_side = "LONG" if position_amt > 0 else "SHORT"

        bullets_pos, bullets_margin = determine_action(roi)

        order_result  = None
        margin_result = None

        if bullets_pos > 0:
            bullets_usdt = bullets_pos * BULLET_SIZE
            quantity     = calculate_quantity(bullets_usdt, mark_price, symbol)
            try:
                order_result = place_limit_order(symbol, position_side, quantity, mark_price)
                order_result["_bullets_pos"]  = bullets_pos
                order_result["_bullets_usdt"] = bullets_usdt
                order_result["_quantity"]      = quantity
                order_result["_price"]         = mark_price
            except Exception as e:
                order_result = {"code": -1, "error": str(e)}

        if bullets_margin > 0:
            margin_usdt = bullets_margin * BULLET_SIZE
            try:
                margin_result = add_margin(symbol, position_side, margin_usdt)
                margin_result["_bullets_margin"] = bullets_margin
                margin_result["_margin_usdt"]    = margin_usdt
            except Exception as e:
                margin_result = {"code": -1, "error": str(e)}

        return {
            "symbol":            symbol,
            "has_position":      True,
            "unrealized_profit": unrealized_profit,
            "initial_margin":    initial_margin,
            "mark_price":        mark_price,
            "avg_price":         avg_price,
            "position_amt":      position_amt,
            "leverage":          leverage,
            "liquidation_price": liquidation_price,
            "roi":               roi,
            "position_side":     position_side,
            "bullets_pos":       bullets_pos,
            "bullets_margin":    bullets_margin,
            "order_result":      order_result,
            "margin_result":     margin_result,
        }

    except Exception as e:
        return {"symbol": symbol, "has_position": None, "error": str(e)}


# ── Email formatting ───────────────────────────────────────────────────────────

def format_pair_html(result: dict) -> str:
    symbol = result.get("symbol", "N/A")

    if result.get("has_position") is None:
        # Error al consultar
        error_msg = result.get("error", "Error desconocido")
        return f"""
    <div style="border-left:4px solid #dc2626;padding:12px 16px;margin-bottom:16px;background:#fef2f2;border-radius:4px;">
      <strong style="color:#dc2626;">{symbol} — Error</strong>
      <p style="margin:4px 0 0;color:#7f1d1d;font-size:13px;">{error_msg}</p>
    </div>
    """

    if not result.get("has_position"):
        return f"""
    <div style="border-left:4px solid #64748b;padding:12px 16px;margin-bottom:16px;background:#f8fafc;border-radius:4px;">
      <strong style="color:#64748b;">{symbol}</strong>
      <p style="margin:4px 0 0;color:#94a3b8;font-size:13px;">No hay posición abierta</p>
    </div>
    """

    roi           = result["roi"]
    roi_color     = "#16a34a" if roi >= 0 else "#dc2626"
    pnl           = result["unrealized_profit"]
    pnl_color     = "#16a34a" if pnl >= 0 else "#dc2626"
    side          = result["position_side"]
    side_color    = "#16a34a" if side == "LONG" else "#dc2626"
    side_label    = f"LONG ▲" if side == "LONG" else f"SHORT ▼"
    size          = abs(result["position_amt"])
    leverage      = result["leverage"]
    avg_price     = result["avg_price"]
    mark_price    = result["mark_price"]
    liq_price     = result["liquidation_price"]
    margin        = result["initial_margin"]

    # Order row
    order_html = ""
    if result["order_result"] is not None:
        r = result["order_result"]
        bp  = r.get("_bullets_pos", result["bullets_pos"])
        bu  = r.get("_bullets_usdt", bp * BULLET_SIZE)
        qty = r.get("_quantity", "?")
        px  = r.get("_price", mark_price)
        ok  = r.get("code") == 0
        icon = "✅" if ok else "❌"
        dry  = " (DRY RUN)" if r.get("dry_run") else ""
        order_id = r.get("data", {}).get("orderId", "") if isinstance(r.get("data"), dict) else ""
        order_id_str = f" · orderId: {order_id}" if order_id else ""
        order_html = f"""
        <tr style="background:#f0fdf4;">
          <td style="padding:6px 14px;color:#64748b;">Orden LIMIT{dry}</td>
          <td style="padding:6px 14px;">{icon} {bp} balas × {BULLET_SIZE:.2f} USDT = {bu:.2f} USDT → {qty} unidades @ {px:.4f}{order_id_str}</td>
        </tr>"""

    # Margin row
    margin_html = ""
    if result["margin_result"] is not None:
        r = result["margin_result"]
        bm  = r.get("_bullets_margin", result["bullets_margin"])
        mu  = r.get("_margin_usdt", bm * BULLET_SIZE)
        ok  = r.get("code") == 0
        icon = "✅" if ok else "❌"
        dry  = " (DRY RUN)" if r.get("dry_run") else ""
        margin_html = f"""
        <tr>
          <td style="padding:6px 14px;color:#64748b;">Margen adicional{dry}</td>
          <td style="padding:6px 14px;">{icon} {bm} balas × {BULLET_SIZE:.2f} USDT = {mu:.2f} USDT</td>
        </tr>"""

    # No action
    no_action_html = ""
    if result["order_result"] is None and result["margin_result"] is None:
        no_action_html = """
        <tr style="background:#fefce8;">
          <td style="padding:6px 14px;color:#64748b;">Acción</td>
          <td style="padding:6px 14px;color:#a16207;">Sin acción (ROI positivo o neutral)</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-family:monospace;font-size:13px;">
      <thead>
        <tr style="background:#1e293b;color:#f1f5f9;">
          <th colspan="2" style="padding:10px 14px;text-align:left;">{symbol} — <span style="color:{side_color};">{side_label}</span> · {leverage}x</th>
        </tr>
      </thead>
      <tbody>
        <tr style="background:#f8fafc;">
          <td style="padding:6px 14px;color:#64748b;">Tamaño / Entry</td>
          <td style="padding:6px 14px;">{size} @ {avg_price:.4f} USDT</td>
        </tr>
        <tr>
          <td style="padding:6px 14px;color:#64748b;">Mark / Liq.</td>
          <td style="padding:6px 14px;">{mark_price:.4f} / {liq_price:.4f} USDT</td>
        </tr>
        <tr style="background:#f8fafc;">
          <td style="padding:6px 14px;color:#64748b;">Margen</td>
          <td style="padding:6px 14px;">{margin:.2f} USDT</td>
        </tr>
        <tr>
          <td style="padding:6px 14px;color:#64748b;">PnL / ROI</td>
          <td style="padding:6px 14px;font-weight:bold;">
            <span style="color:{pnl_color};">{pnl:+.4f} USDT</span>
            &nbsp;
            <span style="color:{roi_color};">({roi:+.2f}%)</span>
          </td>
        </tr>
        {order_html}
        {margin_html}
        {no_action_html}
      </tbody>
    </table>
    """

def build_dca_email_html(results: list, timestamp: str) -> str:
    pairs_html = "".join(format_pair_html(r) for r in results)
    dry_badge  = (
        '<span style="background:#f59e0b;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;">DRY RUN</span>'
        if DRY_RUN else
        '<span style="background:#16a34a;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;">LIVE</span>'
    )

    return f"""
    <div style="font-family:sans-serif;max-width:620px;margin:auto;padding:24px;background:#ffffff;">
      <h2 style="margin:0 0 4px;color:#0f172a;">BingX — Reporte DCA</h2>
      <p style="margin:0 0 6px;color:#64748b;font-size:13px;">{timestamp}</p>
      <p style="margin:0 0 24px;font-size:13px;color:#334155;">
        Capital: <strong>{CAPITAL:.2f} USDT</strong> &nbsp;|&nbsp;
        Bala: <strong>{BULLET_SIZE:.2f} USDT</strong> &nbsp;|&nbsp;
        {dry_badge}
      </p>

      {pairs_html}

      <p style="margin-top:24px;color:#94a3b8;font-size:11px;text-align:center;">
        BingX DCA · GitHub Actions
      </p>
    </div>
    """


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    print(f"BingX DCA — {timestamp}")
    print(f"Capital: {CAPITAL:.2f} USDT | Bala: {BULLET_SIZE:.2f} USDT")
    if DRY_RUN:
        print("⚠️  DRY_RUN activado — no se ejecutarán órdenes reales")

    results = [process_pair(symbol) for symbol in TARGET_PAIRS]

    subject = "BingX | Reporte DCA | ADA-USDT + ETH-USDT"
    if DRY_RUN:
        subject = "[DRY RUN] " + subject
    html = build_dca_email_html(results, timestamp)
    send_email(subject, html)
    print("Email enviado.")


if __name__ == "__main__":
    main()
