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
print(f"✅ Connected to Supabase project: {SUPABASE_URL.split('//')[1].split('.')[0]} (BTS)")


# =====================================================
# 📘 SETTINGS – doar boti BUY_SELL
# =====================================================
def get_latest_settings():
    """Returnează toate setările active BTS (BUY_SELL) din 'settings'."""
    try:
        data = supabase.table("settings").select("*").eq("active", True).execute()
        bots = data.data or []
        bots = [b for b in bots if str(b.get("strategy", "")).upper() in ("BUY_SELL", "BTS")]
        print(f"♻️ Reloaded {len(bots)} active BTS setting(s) from Supabase.")
        return bots
    except Exception as e:
        print(f"❌ Error reading latest settings (BTS): {e}")
        return []


# =====================================================
# 💾 Salvare ordine (strategie BUY → SELL)
# =====================================================
def save_order(symbol, side, price, status, extra=None):
    """Salvează un ordin în tabelul 'orders' pentru strategia BUY → SELL (BTS)."""
    data = {
        "symbol": symbol,
        "side": side,
        "price": float(price),
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "strategy": "BUY_SELL",
    }

    # BUY → ciclu nou dacă nu avem deja cycle_id
    if side.upper() == "BUY" and not (extra and extra.get("cycle_id")):
        data["cycle_id"] = str(uuid.uuid4())

    # Extra meta (order_id, cycle_id, etc.)
    if extra:
        data.update(extra)

    supabase.table("orders").insert(data).execute()
    print(
        f"[BTS][{symbol}] 💾 Saved {side} ({status}) | price={price} | cycle_id={data.get('cycle_id')}"
    )


# =====================================================
# 💰 Profit per cycle (BUY → SELL, profit în COIN)
# =====================================================
def update_execution_time_and_profit(cycle_id: str):
    """
    Calculează durata și profitul efectiv pentru un ciclu BUY → SELL (BTS).
    Profitul se calculează în COIN (nu în USDT).
    """
    try:
        result = (
            supabase.table("orders")
            .select("side, price, created_at, last_updated, symbol, filled_size, strategy")
            .eq("cycle_id", cycle_id)
            .eq("strategy", "BUY_SELL")
            .eq("status", "executed")
            .execute()
        )
        orders = result.data or []
        if len(orders) < 2:
            print(f"[BTS] ⚠️ Skipping profit calc: incomplete cycle {cycle_id}")
            return

        # Separăm BUY / SELL și ignorăm ordinele fără preț
        buys = [
            o for o in orders
            if str(o["side"]).upper() == "BUY" and float(o.get("price") or 0) > 0
        ]
        sells = [
            o for o in orders
            if str(o["side"]).upper() == "SELL" and float(o.get("price") or 0) > 0
        ]

        if not buys or not sells:
            print(f"[BTS] ⚠️ Missing BUY/SELL prices for cycle {cycle_id}")
            return

        # Entry = primul BUY, Exit = ultimul SELL
        first_buy = sorted(buys, key=lambda o: o["created_at"])[0]
        last_sell = sorted(sells, key=lambda o: o["created_at"])[-1]

        symbol = first_buy["symbol"]
        buy_price = float(first_buy["price"])
        sell_price = float(last_sell["price"])

        buy_time = datetime.fromisoformat(
            (first_buy.get("last_updated") or first_buy["created_at"]).replace("Z", "+00:00")
        )
        sell_time = datetime.fromisoformat(
            (last_sell.get("last_updated") or last_sell["created_at"]).replace("Z", "+00:00")
        )

        buy_qty = float(first_buy.get("filled_size") or 0)
        sell_qty = float(last_sell.get("filled_size") or 0)

        qty = 0.0
        if buy_qty > 0 and sell_qty > 0:
            qty = min(buy_qty, sell_qty)
        else:
            qty = max(buy_qty, sell_qty)

        if buy_price <= 0 or sell_price <= 0 or qty <= 0:
            print(f"[BTS] ⚠️ Invalid prices/qty for cycle {cycle_id}")
            return

        # Profit în COIN
        profit_percent = round(((sell_price - buy_price) / buy_price) * 100, 2)
        profit_coin = round((sell_price - buy_price) / buy_price * qty, 6)
        profit_usdt = 0.0  # pentru BTS nu ne interesează USDT

        execution_time = abs(sell_time - buy_time)

        supabase.table("profit_per_cycle").upsert(
            {
                "cycle_id": cycle_id,
                "symbol": symbol,
                "strategy": "BUY_SELL",
                "sell_price": sell_price,
                "buy_price": buy_price,
                "profit_percent": profit_percent,
                "profit_coin": profit_coin,
                "profit_usdt": profit_usdt,
                "execution_time": str(execution_time),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()

        print(
            f"💰 [BTS][{symbol}] cycle {cycle_id} → {profit_percent}% | COIN={profit_coin}"
        )

    except Exception as e:
        print(f"❌ [BTS] Error updating profit for {cycle_id}: {e}")
