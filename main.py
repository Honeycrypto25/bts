import time
import uuid
import os
import logging
from datetime import datetime, timezone
from exchange import (
    init_client,
    market_sell,
    check_order_executed,
    place_limit_buy,
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
    filename="logs/stb.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

logging.info("🚀 STB BOT (Sell-Then-Buy) started...\n")

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
            logging.info(f"[{symbol}] ✅ SELL executat @ {avg_price}")
            return True, avg_price

        if time.time() - start_ts > MARKET_TIMEOUT_SECONDS:
            logging.warning(
                f"[{symbol}] ⏰ Timeout la MARKET SELL — ordinul rămâne pending. Trec peste ciclul curent."
            )
            return False, 0
    return False, 0

# =====================================================
# 🤖 Bot principal STB
# =====================================================
def run_bot(settings):
    symbol = settings["symbol"]
    amount = float(settings["amount"])
    buy_discount = float(settings["buy_discount"])
    check_delay = int(settings["check_delay"])
    cycle_delay = int(settings["cycle_delay"])
    api_key = settings["api_key"]
    api_secret = settings["api_secret"]
    api_passphrase = settings["api_passphrase"]

    # normalizează discount (acceptă 5 sau 0.05)
    if buy_discount > 1:
        buy_discount = buy_discount / 100.0

    logging.info(
        f"[{symbol}] ⚙️ STB bot started | amount={amount}, discount={buy_discount*100:.2f}%, cycle={cycle_delay/3600}h"
    )

    while True:
        try:
            bots = get_latest_settings()
            for bot in bots:
                if bot["symbol"] == symbol:
                    settings = bot
                    buy_discount = float(bot["buy_discount"])
                    if buy_discount > 1:
                        buy_discount = buy_discount / 100.0
                    cycle_delay = int(bot["cycle_delay"])
                    break

            client = init_client(api_key, api_secret, api_passphrase)
            cycle_id = str(uuid.uuid4())
            logging.info(f"[{symbol}] 🧠 New STB cycle {cycle_id} started...")

            # =====================================================
            # 1️⃣ SELL MARKET
            # =====================================================
            sell_id = market_sell(client, symbol, amount, "STB")
            if not sell_id:
                logging.warning(f"[{symbol}] ⚠️ Market SELL failed — skipping cycle.")
                time.sleep(cycle_delay)
                continue

            safe_save_order(
                symbol, "SELL", 0, "pending",
                {"order_id": sell_id, "cycle_id": cycle_id, "strategy": "STB"}
            )

            ok, avg_price = wait_market_execution(client, symbol, sell_id, amount, check_delay, cycle_id)
            if not ok or avg_price <= 0:
                time.sleep(cycle_delay)
                continue

            # =====================================================
            # 2️⃣ BUY LIMIT
            # =====================================================
            buy_price = adjust_price_to_tick(avg_price * (1 - buy_discount))
            buy_id = place_limit_buy(client, symbol, amount, buy_price, "STB")
            if not buy_id:
                logging.warning(f"[{symbol}] ⚠️ Limit BUY failed — skipping cycle.")
                time.sleep(cycle_delay)
                continue

            safe_save_order(
                symbol, "BUY", buy_price, "open",
                {"order_id": buy_id, "cycle_id": cycle_id, "strategy": "STB"}
            )
            logging.info(f"[{symbol}] 🟢 BUY limit placed @ {buy_price} (−{buy_discount*100:.2f}%)")

            # =====================================================
            # 3️⃣ Aștept ciclul următor
            # =====================================================
            logging.info(f"[{symbol}] ⏳ Cycle complete → waiting {cycle_delay/3600}h\n")
            time.sleep(cycle_delay)

        except Exception as e:
            logging.error(f"[{symbol}] ❌ Error: {e}")
            time.sleep(30)

# =====================================================
# 🚀 Start bot
# =====================================================
def start_stb_bot():
    bots = get_latest_settings()
    if not bots:
        logging.warning("⚠️ No active bots found in Supabase.")
        return

    for settings in bots:
        threading = None
        run_bot(settings)

if __name__ == "__main__":
    start_stb_bot()
