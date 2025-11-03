import time
import threading
import uuid
import os
import logging
from datetime import datetime, timezone
from exchange import (
    init_client,
    market_buy,
    check_order_executed,
    place_limit_sell,
)
from supabase_client import (
    get_latest_settings,
    save_order,
    supabase,
    update_execution_time_and_profit,
)

# =====================================================
# 🪵 Setup logging
# =====================================================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/bts.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

logging.info("🚀 BTS BOT (Buy-Then-Sell) started...\n")

# =====================================================
# ⚙️ Constante
# =====================================================
MARKET_TIMEOUT_SECONDS = 600  # 10 minute max pentru execuție MARKET
TICK_SIZE = 0.00001  # pentru HONEY-USDT

# =====================================================
# 🧮 Tick Size Adjust
# =====================================================
def adjust_price_to_tick(price, tick_size=TICK_SIZE):
    return round(round(price / tick_size) * tick_size, 5)

# =====================================================
# 💾 Save wrapper
# =====================================================
def safe_save_order(symbol, side, price, status, meta):
    try:
        save_order(symbol, side, price, status, meta)
        logging.info(
            f"[{symbol}] 💾 Saved {side} ({status}) | price={price} | cycle_id={meta.get('cycle_id')}"
        )
    except Exception as e:
        logging.error(f"[{symbol}] ❌ save_order failed: {e}")

# =====================================================
# ⏱️ Helper: așteaptă execuția MARKET cu timeout
# =====================================================
def wait_market_execution(client, symbol, order_id, amount, check_delay, cycle_id):
    start_ts = time.time()
    executed, avg_price = False, 0
    while not executed:
        time.sleep(check_delay)
        executed, avg_price = check_order_executed(client, order_id)
        if executed:
            supabase.table("orders").update(
                {
                    "status": "executed",
                    "price": avg_price,
                    "filled_size": amount,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("order_id", order_id).execute()
            logging.info(f"[{symbol}] ✅ BUY executat @ {avg_price}")
            return True, avg_price

        if time.time() - start_ts > MARKET_TIMEOUT_SECONDS:
            logging.warning(
                f"[{symbol}] ⏰ Timeout la MARKET BUY — ordinul rămâne pending. Trec peste ciclul curent."
            )
            return False, 0
    return False, 0

# =====================================================
# 🧠 Verificare ordine vechi (pending/open)
# =====================================================
def update_order_status(order_id, new_status, avg_price=None, filled_size=None, cycle_id=None):
    data = {
        "status": new_status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if avg_price is not None:
        data["price"] = avg_price
    if filled_size is not None:
        data["filled_size"] = filled_size

    supabase.table("orders").update(data).eq("order_id", order_id).execute()
    logging.info(f"🟢 Updated {order_id}: {new_status} ({avg_price})")

    if new_status == "executed" and cycle_id:
        update_execution_time_and_profit(cycle_id)


def check_old_orders(client, symbol):
    result = (
        supabase.table("orders")
        .select("*")
        .eq("symbol", symbol)
        .in_("status", ["pending", "open"])
        .order("last_updated", desc=False)
        .limit(5)
        .execute()
    )
    orders = result.data or []
    if not orders:
        logging.info(f"[{symbol}] ✅ Nicio comandă veche de verificat.")
        return

    for order in orders:
        order_id = order.get("order_id")
        cycle_id = order.get("cycle_id")
        side = order.get("side")
        if not order_id:
            continue

        done, avg_price = check_order_executed(client, order_id)
        if done:
            update_order_status(order_id, "executed", avg_price, None, cycle_id)
            logging.info(f"[{symbol}] ✅ Ordin {side} executat: {order_id}")
        else:
            update_order_status(order_id, "pending")
            logging.info(f"[{symbol}] ⏳ Ordin {side} încă în așteptare: {order_id}")

def run_order_checker():
    while True:
        try:
            bots = get_latest_settings()
            if not bots:
                logging.warning("⚠️ Niciun bot activ în settings.")
                time.sleep(3600)
                continue

            logging.info(f"\n🔍 Pornesc verificarea la {datetime.now(timezone.utc).isoformat()}...\n")
            for bot in bots:
                symbol = bot["symbol"]
                client = init_client(bot["api_key"], bot["api_secret"], bot["api_passphrase"])
                check_old_orders(client, symbol)

            logging.info("✅ Verificarea s-a terminat. Următoarea în 1 oră.\n")
            time.sleep(3600)
        except Exception as e:
            logging.error(f"❌ Eroare în order_checker: {e}")
            time.sleep(60)

# =====================================================
# 🤖 Bot principal BTS
# =====================================================
def run_bot(settings):
    symbol = settings["symbol"]
    amount = float(settings["amount"])
    sell_bonus = float(settings["buy_discount"])  # reuse field as sell % bonus
    check_delay = int(settings["check_delay"])
    cycle_delay = int(settings["cycle_delay"])
    api_key = settings["api_key"]
    api_secret = settings["api_secret"]
    api_passphrase = settings["api_passphrase"]

    if sell_bonus > 1:
        sell_bonus = sell_bonus / 100.0

    logging.info(
        f"[{symbol}] ⚙️ BTS bot started | amount={amount}, sell+={sell_bonus*100:.2f}%, cycle={cycle_delay/3600}h"
    )

    while True:
        try:
            bots = get_latest_settings()
            for bot in bots:
                if bot["symbol"] == symbol:
                    settings = bot
                    sell_bonus = float(bot["buy_discount"])
                    if sell_bonus > 1:
                        sell_bonus = sell_bonus / 100.0
                    cycle_delay = int(bot["cycle_delay"])
                    break

            client = init_client(api_key, api_secret, api_passphrase)
            cycle_id = str(uuid.uuid4())
            logging.info(f"[{symbol}] 🧠 New BTS cycle {cycle_id} started...")

            # =====================================================
            # 1️⃣ BUY MARKET
            # =====================================================
            buy_id = market_buy(client, symbol, amount, "BTS")
            if not buy_id:
                logging.warning(f"[{symbol}] ⚠️ Market BUY failed — skipping cycle.")
                time.sleep(cycle_delay)
                continue

            safe_save_order(
                symbol, "BUY", 0, "pending",
                {"order_id": buy_id, "cycle_id": cycle_id, "strategy": "BTS"}
            )

            ok, avg_price = wait_market_execution(client, symbol, buy_id, amount, check_delay, cycle_id)
            if not ok or avg_price <= 0:
                time.sleep(cycle_delay)
                continue

            # =====================================================
            # 2️⃣ SELL LIMIT
            # =====================================================
            sell_price = adjust_price_to_tick(avg_price * (1 + sell_bonus))
            sell_id = place_limit_sell(client, symbol, amount, sell_price, "BTS")
            if not sell_id:
                logging.warning(f"[{symbol}] ⚠️ Limit SELL failed — skipping cycle.")
                time.sleep(cycle_delay)
                continue

            safe_save_order(
                symbol, "SELL", sell_price, "open",
                {"order_id": sell_id, "cycle_id": cycle_id, "strategy": "BTS"}
            )
            logging.info(f"[{symbol}] 🔴 SELL limit placed @ {sell_price} (+{sell_bonus*100:.2f}%)")

            logging.info(f"[{symbol}] ⏳ Cycle complete → waiting {cycle_delay/3600}h\n")
            time.sleep(cycle_delay)

        except Exception as e:
            logging.error(f"[{symbol}] ❌ Error: {e}")
            time.sleep(30)

# =====================================================
# 🚀 Start bot + checker în paralel
# =====================================================
def start_bts_bot():
    bots = get_latest_settings()
    if not bots:
        logging.warning("⚠️ No active bots found in Supabase.")
        return

    # Pornește fiecare bot separat
    for settings in bots:
        threading.Thread(target=run_bot, args=(settings,), daemon=True).start()
        logging.info(f"🕒 Delay 10s înainte de următorul bot...")
        time.sleep(10)

    # Pornește checkerul într-un thread separat
    threading.Thread(target=run_order_checker, daemon=True).start()

    while True:
        time.sleep(60)

if __name__ == "__main__":
    start_bts_bot()
