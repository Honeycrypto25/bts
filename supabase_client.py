import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

# =====================================================
# 🔌 Load environment variables (.env)
# =====================================================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ Missing SUPABASE_URL or SUPABASE_KEY. Check your .env file.")

# =====================================================
# ⚙️ Create Supabase client
# =====================================================
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
print(f"✅ Connected to Supabase project: {SUPABASE_URL.split('//')[1].split('.')[0]}")

# =====================================================
# 📘 SETTINGS
# =====================================================
def get_latest_settings():
    """Returnează toate setările active din 'settings'."""
    try:
        data = supabase.table("settings").select("*").eq("active", True).execute()
        bots = data.data or []
        print(f"♻️ Reloaded {len(bots)} active setting(s) from Supabase.")
        return bots
    except Exception as e:
        print(f"❌ Error reading latest settings: {e}")
        return []

# =====================================================
# 💾 Salvare ordine (strategie BUY → SELL)
# =====================================================
def save_order(symbol, side, price, status, extra=None):
    """Salvează un ordin în tabelul 'orders' pentru strategia BUY → SELL."""
    data = {
        "symbol": symbol,
        "side": side,
        "price": float(price),
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "strategy": "BUY_SELL",
    }

    # BUY → ciclu nou
    if side.upper() == "BUY":
        data["cycle_id"] = str(uuid.uuid4())

    # SELL → continuă ciclul existent
    if extra and "cycle_id" in extra:
        data["cycle_id"] = extra["cycle_id"]

    if extra:
        data.update(extra)

    supabase.table("orders").insert(data).execute()
    print(
        f"[{symbol}] 💾 Saved {side} ({status}) | price={price} | cycle_id={data.get('cycle_id')}"
    )

# =====================================================
# 💰 Profit per cycle (BUY → SELL)
# =====================================================
def update_execution_time_and_profit(cycle_id):
    """Calculează durata și profitul efectiv pentru fiecare ciclu BUY → SELL."""
    try:
        result = (
            supabase.table("orders")
            .select("side, price, created_at, last_updated, symbol, filled_size")
            .eq("cycle_id", cycle_id)
            .execute()
        )
        orders = result.data or []
        if len(orders) < 2:
            print(f"⚠️ Skipping execution_time: incomplete cycle {cycle_id}")
            return

        symbol = None
        buy_price = sell_price = buy_time = sell_time = filled_size = None

        for o in orders:
            symbol = o["symbol"]
            side = o["side"].upper()
            price = float(o["price"])
            filled = float(o.get("filled_size") or 0)
            ts = datetime.fromisoformat(
                (o.get("last_updated") or o.get("created_at")).replace("Z", "+00:00")
            )

            if side == "BUY":
                buy_price = price
                buy_time = ts
                filled_size = filled
            elif side == "SELL":
                sell_price = price
                sell_time = ts
                filled_size = filled

        if not (sell_price and buy_price):
            print(f"⚠️ Missing price data for {cycle_id}")
            return

        # ✅ Profit doar în COIN (pentru strategia BUY → SELL)
        profit_percent = round(((sell_price - buy_price) / buy_price) * 100, 2)
        profit_coin = round((sell_price - buy_price) / buy_price * filled_size, 6)
        profit_usdt = None  # nu se calculează pentru BTS

        # ⏱️ Durata execuției
        execution_time = abs(sell_time - buy_time) if (sell_time and buy_time) else None

        # 🧾 Salvare / actualizare în profit_per_cycle
        supabase.table("profit_per_cycle").upsert({
            "cycle_id": cycle_id,
            "symbol": symbol,
            "strategy": "BUY_SELL",
            "sell_price": sell_price,
            "buy_price": buy_price,
            "profit_percent": profit_percent,
            "profit_coin": profit_coin,
            "profit_usdt": profit_usdt,
            "execution_time": str(execution_time) if execution_time else None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }).execute()

        print(f"💰 [{symbol}] Profit updated: {profit_percent}% → COIN={profit_coin}")

    except Exception as e:
        print(f"❌ Error updating profit for {cycle_id}: {e}")
