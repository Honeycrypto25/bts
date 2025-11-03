from kucoin.client import Trade
import time
import random

# =====================================================
# 🔌 Inițializare client KuCoin
# =====================================================
def init_client(api_key, api_secret, api_passphrase):
    """Creează conexiunea la KuCoin Trade API."""
    try:
        client = Trade(key=api_key, secret=api_secret, passphrase=api_passphrase)
        print("✅ KuCoin client initialized.")
        return client
    except Exception as e:
        print(f"❌ Eroare la inițializarea clientului KuCoin: {e}")
        raise

# =====================================================
# 🧱 Funcție generală de retry (stabilitate 24/7)
# =====================================================
def safe_order(action_func, *args, retries=3, delay=5, **kwargs):
    """Reîncearcă o acțiune KuCoin până la 3 ori dacă apare eroare temporară."""
    for attempt in range(1, retries + 1):
        try:
            return action_func(*args, **kwargs)
        except Exception as e:
            print(f"⚠️ Eroare la încercarea {attempt}/{retries}: {e}")
            if attempt < retries:
                sleep_time = delay + random.uniform(0, 3)
                print(f"⏳ Reîncerc în {round(sleep_time, 1)}s...")
                time.sleep(sleep_time)
            else:
                print("❌ Toate încercările au eșuat.")
                return None

# =====================================================
# 💰 Market SELL (prima acțiune din strategia STB)
# =====================================================
def market_sell(client, symbol, amount, strategy_label="STB"):
    """Plasează un ordin de vânzare MARKET."""
    def action():
        order = client.create_market_order(symbol, 'sell', size=str(amount))
        return order.get('orderId') or order.get('id')

    order_id = safe_order(action)
    if order_id:
        print(f"[{symbol}][{strategy_label}] 🟠 Market SELL placed (orderId: {order_id})")
    else:
        print(f"[{symbol}][{strategy_label}] ❌ Market SELL failed after retries.")
    return order_id

# =====================================================
# 🔍 Verificare status ordin
# =====================================================
def check_order_executed(client, order_id):
    """Verifică dacă un ordin a fost complet executat."""
    try:
        if hasattr(client, "get_order_details"):
            status = client.get_order_details(order_id)
        else:
            status = client.get_order(order_id)

        filled = float(status.get('dealSize', 0))
        total = float(status.get('size', 0))
        deal_funds = float(status.get('dealFunds', 0))
        state = status.get('status', '')
        done = state == 'done' or filled >= total
        avg_price = (deal_funds / filled) if filled > 0 else 0

        symbol = status.get('symbol', '')
        print(f"[{symbol}] 🔎 check_order_executed → {state} {filled}/{total} avg={avg_price}")
        return done, avg_price
    except Exception as e:
        print(f"❌ Eroare la check_order_executed pentru {order_id}: {e}")
        time.sleep(5)
        return False, 0

# =====================================================
# 🟢 Limit BUY (a doua acțiune din strategia STB)
# =====================================================
def place_limit_buy(client, symbol, amount, price, strategy_label="STB"):
    """Plasează un ordin de cumpărare LIMIT."""
    def action():
        order = client.create_limit_order(symbol, 'buy', size=str(amount), price=str(price))
        return order.get('orderId') or order.get('id')

    order_id = safe_order(action)
    if order_id:
        print(f"[{symbol}][{strategy_label}] 🟢 Limit BUY @ {price} (id: {order_id})")
    else:
        print(f"[{symbol}][{strategy_label}] ❌ Limit BUY failed after retries.")
    return order_id
