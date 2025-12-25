import os, time, sqlite3, traceback
from datetime import datetime
import telebot
from telebot import types
import os
import sqlite3

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing/invalid. Put it in start.sh (must contain ':').")
if ADMIN_ID <= 0:
    raise ValueError("ADMIN_ID missing/invalid. Put it in start.sh.")

DB_FILE = os.path.join(os.path.dirname(__file__), "shopbot.db")
FILES_BOT_URL = "https://t.me/panel_updates_bot"

ESIGN_PRODUCT_KEY = "ESIGN_CERT"
ESIGN_DAYS = 365

# products (FLOURITE durations: 1/7/30 per your fix)
PRODUCTS = {
    "DRIP_CLIENT": {"label": "DRIP CLIENT", "platforms": [("ANDROID NON ROOT","AND_NR")], "durations": [1,7,15,30], "type": "code"},
    "FLOURITE": {"label": "FLOURITE", "platforms": [("IOS","IOS")], "durations": [1,7,30], "type": "code"},
    "HG_CHEATS": {"label": "HG CHEATS", "platforms": [("ANDROID NON ROOT","AND_NR")], "durations": [1,10,30], "type": "code"},
    "CODM": {"label": "CODM", "platforms": [("IOS","IOS")], "durations": [7,30], "type": "code"},
    "ESIGN_CERT": {"label": "ESIGN CERTIFICAT", "platforms": [("IOS","IOS")], "durations": [365], "type": "request"},
}
    # Special request product (no code delivered)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)


# Remember last inline message per user so we can delete it when user goes to main menu

# simple state (admin addstock paste / user esign udid)

STATE = {}  # uid -> dict (state)

def remember_inline(uid: int, chat_id: int, msg_id: int):
    STATE.setdefault(uid, {})
    STATE[uid]["last_inline"] = (chat_id, msg_id)

def delete_last_inline(uid: int):
    try:
        v = STATE.get(uid, {}).get("last_inline")
        if not v:
            return
        chat_id, msg_id = v
        bot.delete_message(chat_id, msg_id)
        STATE[uid].pop("last_inline", None)
    except Exception:
        pass

def now_utc():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def db():
    return sqlite3.connect(DB_FILE)

def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        uid INTEGER PRIMARY KEY,
        balance REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS prices(
        product TEXT NOT NULL,
        days INTEGER NOT NULL,
        price REAL NOT NULL,
        PRIMARY KEY(product, days)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS stock_codes(
        product TEXT NOT NULL,
        days INTEGER NOT NULL,
        code TEXT NOT NULL
    )""")
    # numeric stock for request-type products (like ESIGN)
    cur.execute("""CREATE TABLE IF NOT EXISTS stock_numbers(
        product TEXT NOT NULL,
        days INTEGER NOT NULL,
        count INTEGER NOT NULL,
        PRIMARY KEY(product, days)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL,
        product TEXT NOT NULL,
        days INTEGER NOT NULL,
        price REAL NOT NULL,
        note TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL,
        product TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    con.commit()
    con.close()

def is_admin(uid: int) -> bool:
    try:
        return int(uid) == int(ADMIN_ID)
    except Exception:
        return False

def ensure_user(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid FROM users WHERE uid=?", (uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users(uid,balance,created_at) VALUES(?,?,?)", (uid, 0.0, now_utc()))
        con.commit()
    con.close()

def get_user(uid: int):
    ensure_user(uid)
    con = db()
    cur = con.cursor()
    cur.execute("SELECT uid, balance, created_at FROM users WHERE uid=?", (uid,))
    row = cur.fetchone()
    con.close()
    return row

def add_balance(uid: int, delta: float):
    ensure_user(uid)
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE users SET balance=balance+? WHERE uid=?", (float(delta), uid))
    con.commit()
    con.close()

def set_price(product: str, days: int, price: float):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO prices(product,days,price) VALUES(?,?,?) "
        "ON CONFLICT(product,days) DO UPDATE SET price=excluded.price",
        (product, int(days), float(price))
    )
    con.commit()
    con.close()

def get_price(product: str, days: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT price FROM prices WHERE product=? AND days=?", (product, int(days)))
    row = cur.fetchone()
    con.close()
    return None if not row else float(row[0])

def add_stock_codes(product: str, days: int, codes):
    codes = [c.strip() for c in codes if c.strip()]
    if not codes:
        return 0
    con = db()
    cur = con.cursor()
    cur.executemany("INSERT INTO stock_codes(product,days,code) VALUES(?,?,?)",
                    [(product, int(days), c) for c in codes])
    con.commit()
    con.close()
    return len(codes)

def pop_code(product: str, days: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT rowid, code FROM stock_codes WHERE product=? AND days=? LIMIT 1", (product, int(days)))
    row = cur.fetchone()
    if not row:
        con.close()
        return None
    rowid, code = row
    cur.execute("DELETE FROM stock_codes WHERE rowid=?", (rowid,))
    con.commit()
    con.close()
    return code

def count_codes(product: str, days: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM stock_codes WHERE product=? AND days=?", (product, int(days)))
    n = int(cur.fetchone()[0])
    con.close()
    return n

def set_stock_number(product: str, days: int, count: int):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO stock_numbers(product,days,count) VALUES(?,?,?) "
        "ON CONFLICT(product,days) DO UPDATE SET count=excluded.count",
        (product, int(days), int(count))
    )
    con.commit()
    con.close()

def get_stock_number(product: str, days: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT count FROM stock_numbers WHERE product=? AND days=?", (product, int(days)))
    row = cur.fetchone()
    con.close()
    return 0 if not row else int(row[0])

def record_sale(uid: int, product: str, days: int, price: float, note: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO sales(uid,product,days,price,note,created_at) VALUES(?,?,?,?,?,?)",
        (uid, product, int(days), float(price), note, now_utc())
    )
    con.commit()
    con.close()

def user_stats(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM sales WHERE uid=?", (uid,))
    n, s = cur.fetchone()
    con.close()
    return int(n), float(s)

def last_purchases(uid: int, limit: int = 5):
    con = db()
    cur = con.cursor()
    cur.execute(
        "SELECT product, days, price, note, created_at "
        "FROM sales WHERE uid=? ORDER BY id DESC LIMIT ?",
        (uid, int(limit))
    )
    rows = cur.fetchall()
    con.close()
    return rows

def admin_dashboard():
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users_n = int(cur.fetchone()[0])
    cur.execute("SELECT COALESCE(SUM(balance),0) FROM users")
    bal_sum = float(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM sales")
    sales_n, sales_sum = cur.fetchone()
    sales_n, sales_sum = int(sales_n), float(sales_sum or 0)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*), COALESCE(SUM(price),0) FROM sales WHERE created_at LIKE ?", (today + "%",))
    t_n, t_sum = cur.fetchone()
    t_n, t_sum = int(t_n), float(t_sum or 0)
    cur.execute("SELECT uid, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall()
    con.close()
    return users_n, bal_sum, sales_n, sales_sum, t_n, t_sum, top

def main_menu_kb(uid: int):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🛍 Buy keys", "🏦 Account")
    kb.row("📦 Stock", "📊 Statistics")
    kb.row("📂 Get Files")
    if is_admin(uid):
        kb.row("🛠 Manage")
    return kb

def kb_products():
    mk = types.InlineKeyboardMarkup()

    for pkey, meta in PRODUCTS.items():
        # ✅ ESIGN (type=request) يظهر حتى لو stock = 0 (باش تبان السلعة)
        # إذا تحب تخليه يبان غير كي stock>0، نبدلو الشرط
        mk.add(types.InlineKeyboardButton(meta["label"], callback_data=f"BUY_P|{pkey}"))

    mk.add(types.InlineKeyboardButton("⬅ Back", callback_data="BUY_BACK_MAIN"))
    return mk

def show_main_menu(chat_id: int, uid: int, text="✅ Bot Online!"):
    delete_last_inline(uid)
    bot.send_message(chat_id, text, reply_markup=main_menu_kb(uid))

def edit_inline(call, text: str, markup):
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    remember_inline(call.from_user.id, call.message.chat.id, call.message.message_id)

# ================= INLINE BUY FLOW =================
def kb_products():
    mk = types.InlineKeyboardMarkup()
    for pkey, meta in PRODUCTS.items():
        # Esign: only show if numeric stock > 0
        mk.add(types.InlineKeyboardButton(meta["label"], callback_data=f"BUY_P|{pkey}"))
    mk.add(types.InlineKeyboardButton("⬅ Back", callback_data="BUY_BACK_MAIN"))
    return mk

def kb_platforms(pkey: str):
    mk = types.InlineKeyboardMarkup()
    for title, plat in PRODUCTS[pkey]["platforms"]:
        mk.add(types.InlineKeyboardButton(title, callback_data=f"BUY_PL|{pkey}|{plat}"))
    mk.add(types.InlineKeyboardButton("⬅ Back", callback_data="BUY_BACK_PRODUCTS"))
    return mk

def kb_durations(pkey: str, plat: str):
    mk = types.InlineKeyboardMarkup()
    meta = PRODUCTS[pkey]
    for days in meta["durations"]:
        price = get_price(pkey, days)

        if meta["type"] == "request":
            stock = get_stock_number(pkey, days)
        else:
            stock = count_codes(pkey, days)

        # disable when missing price or stock=0
        if price is None or stock <= 0:
            label = f"{days} Days — {'price not set' if price is None else f'{price:.2f}$'} — stock {stock}"
            mk.add(types.InlineKeyboardButton(label, callback_data="NOOP"))
        else:
            label = f"{days} Days — {price:.2f}$ — stock {stock}"
            mk.add(types.InlineKeyboardButton(label, callback_data=f"BUY_D|{pkey}|{plat}|{days}"))

    mk.add(types.InlineKeyboardButton("⬅ Back", callback_data=f"BUY_BACK_PLATFORM|{pkey}"))
    return mk

def kb_confirm(pkey: str, plat: str, days: int):
    mk = types.InlineKeyboardMarkup()
    mk.row(
        types.InlineKeyboardButton("✅ Confirm", callback_data=f"BUY_OK|{pkey}|{plat}|{days}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"BUY_PL|{pkey}|{plat}")
    )
    return mk

# ================= MESSAGE HANDLERS =================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)
    delete_last_inline(uid)  # ✅ هذا هو
    show_main_menu(message.chat.id, uid, "✅ Bot Online!")

@bot.message_handler(func=lambda m: m.text == "🏦 Account")
def h_account(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)
    u, bal, created = get_user(uid)
    bot.send_message(
        message.chat.id,
        f"🏦 Account\n\nID: {u}\nBalance: {bal:.2f}$\nCreated: {created}",
        reply_markup=main_menu_kb(uid)
    )

@bot.message_handler(func=lambda m: m.text == "📦 Stock")
def h_stock(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)
    lines = ["📦 Stock:\n"]
    for pkey, meta in PRODUCTS.items():
        lines.append(f"— {meta['label']}")
        for d in meta["durations"]:
            if meta["type"] == "request":
                n = get_stock_number(pkey, d)
                label = "365 Days (year)" if (pkey == "ESIGN_CERT" and d == 365) else f"{d} Days"
                lines.append(f"{label}: {n}")
            else:
                n = count_codes(pkey, d)
                lines.append(f"{d} Days: {n}")
        lines.append("")
    bot.send_message(message.chat.id, "\n".join(lines).strip(), reply_markup=main_menu_kb(uid))

@bot.message_handler(func=lambda m: m.text == "📊 Statistics")
def h_stats(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)

    purchases, spent = user_stats(uid)
    _, bal, _ = get_user(uid)

    rows = last_purchases(uid, 5)

    lines = []
    lines.append("📊 Statistics")
    lines.append(f"Purchases: {purchases}")
    lines.append(f"Total spent: {spent:.2f}$")
    lines.append(f"Balance: {bal:.2f}$")
    lines.append("")
    lines.append("🧾 Last 5 purchases:")

    if not rows:
        lines.append("• (none yet)")
    else:
        for product, days, price, note, created_at in rows:
            label = PRODUCTS.get(product, {}).get("label", product)

            if product == "ESIGN_CERT" or (PRODUCTS.get(product, {}).get("type") == "request"):
                lines.append(f"• {label} — {days} Days — {price:.2f}$ — ✅ تم الطلب")
            else:
                code = (note or "").strip()
                if not code:
                    code = "(no code)"
                lines.append(f"• {label} — {days} Days — {price:.2f}$ — CODE: {code}")

    msg = "\n".join(lines)

    if is_admin(uid):
        users_n, bal_sum, sales_n, sales_sum, t_n, t_sum, top = admin_dashboard()
        top_lines = "\n".join([f"• {u}: {float(b):.2f}$" for (u, b) in top])
        msg += (
            "\n\n👑 Admin Dashboard\n"
            f"Total users: {users_n}\n"
            f"Total user balances: {bal_sum:.2f}$\n"
            f"All-time purchases: {sales_n} | {sales_sum:.2f}$\n"
            f"Today purchases: {t_n} | {t_sum:.2f}$\n\n"
            "Top balances:\n"
            f"{top_lines}\n"
        )

    bot.send_message(message.chat.id, msg, reply_markup=main_menu_kb(uid))

@bot.message_handler(func=lambda m: m.text == "📂 Get Files")
def h_files(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("📌 Open bot", url=FILES_BOT_URL))
    bot.send_message(message.chat.id, "ملفات أي بانل ستجدها في هذا البوت:", reply_markup=mk)

@bot.message_handler(func=lambda m: m.text == "🛍 Buy keys")
def h_buy(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)

    bot.send_message(
        message.chat.id,
        "Choose product:",
        reply_markup=kb_products()
    )

@bot.message_handler(func=lambda m: m.text == "🛠 Manage")
def h_manage(message):
    uid = message.from_user.id
    delete_last_inline(uid)
    ensure_user(uid)
    if not is_admin(uid):
        bot.send_message(message.chat.id, "⛔ Admin only.", reply_markup=main_menu_kb(uid))
        return
    txt = (
        "🛠 Manage\n\n"
        "/addbalance USER_ID AMOUNT\n"
        "/deductbalance USER_ID AMOUNT\n"
        "/setprice PRODUCT DAYS PRICE\n"
        "/addstock PRODUCT DAYS   (then paste codes, one per line)\n"
        "/setstock PRODUCT DAYS COUNT   (for Esign Certificate)\n\n"
        "PRODUCT:\nDRIP_CLIENT / FLOURITE / HG_CHEATS / CODM / ESIGN_CERT\n"
    )
    bot.send_message(message.chat.id, txt, reply_markup=main_menu_kb(uid))

# ================= ADMIN COMMANDS =================
@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin only.")
        return
    try:
        _, user_id, amount = message.text.split(maxsplit=2)
        add_balance(int(user_id), float(amount))
        bot.reply_to(message, f"✅ Added {float(amount):.2f}$ to {user_id}")
    except Exception:
        bot.reply_to(message, "❌ Usage: /addbalance USER_ID AMOUNT")

@bot.message_handler(commands=["deductbalance", "minusbala"])
def cmd_deduct(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin only.")
        return
    try:
        _, user_id, amount = message.text.split(maxsplit=2)
        add_balance(int(user_id), -abs(float(amount)))
        bot.reply_to(message, f"✅ Deducted {abs(float(amount)):.2f}$ from {user_id}")
    except Exception:
        bot.reply_to(message, "❌ Usage: /deductbalance USER_ID AMOUNT")

@bot.message_handler(commands=["setprice"])
def cmd_setprice(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin only.")
        return
    try:
        _, product, days, price = message.text.split(maxsplit=3)
        product = product.strip().upper()
        if product not in PRODUCTS:
            bot.reply_to(message, "❌ Unknown product.")
            return
        set_price(product, int(days), float(price))
        bot.reply_to(message, f"✅ Price set: {product} {days} Days = {float(price):.2f}$")
    except Exception:
        bot.reply_to(message, "❌ Usage: /setprice PRODUCT DAYS PRICE")

@bot.message_handler(commands=["setstock"])
def cmd_setstock(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin only.")
        return
    try:
        _, product, days, count = message.text.split(maxsplit=3)
        product = product.strip().upper()
        days = int(days)
        count = int(count)
        if product not in PRODUCTS:
            bot.reply_to(message, "❌ Unknown product.")
            return
        set_stock_number(product, days, count)
        bot.reply_to(message, f"✅ Stock set: {product} {days} Days = {count}")
    except Exception:
        bot.reply_to(message, "❌ Usage: /setstock PRODUCT DAYS COUNT")

@bot.message_handler(commands=["addstock"])
def cmd_addstock(message):
    uid = message.from_user.id
    if not is_admin(uid):
        bot.reply_to(message, "⛔ Admin only.")
        return
    try:
        _, product, days = message.text.split(maxsplit=2)
        product = product.strip().upper()
        days = int(days)
        if product not in PRODUCTS:
            bot.reply_to(message, "❌ Unknown product.")
            return
        if PRODUCTS[product]["type"] != "code":
            bot.reply_to(message, "❌ This product uses numeric stock. Use /setstock.")
            return
        if days not in PRODUCTS[product]["durations"]:
            bot.reply_to(message, "❌ Duration not configured for this product.")
            return
        STATE[uid] = {"state": "WAIT_CODES", "product": product, "days": days}
        bot.reply_to(message, f"🧾 Paste codes now (one per line) for {product} {days} Days:")
    except Exception:
        bot.reply_to(message, "❌ Usage: /addstock PRODUCT DAYS")

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    uid = message.from_user.id
    if uid in STATE:
        STATE.pop(uid, None)
        bot.reply_to(message, "✅ Cancelled.")
    else:
        bot.reply_to(message, "Nothing to cancel.")

# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    try:
        data = call.data or ""
        uid = call.from_user.id
        ensure_user(uid)

        if data == "NOOP":
            try:
                bot.answer_callback_query(call.id, "❌ Out of stock / price not set.", show_alert=False)
            except Exception:
                pass
            return

        if data == "BUY_BACK_MAIN":
            # احذف رسالة القائمة (Inline) ثم رجع للمينيو
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass

            show_main_menu(call.message.chat.id, uid, "✅ Back to menu.")
            return

        if data == "BUY_BACK_PRODUCTS":
            edit_inline(call, "Choose product:", kb_products())
            return

        if data.startswith("BUY_P|"):
            pkey = data.split("|", 1)[1]
            if pkey not in PRODUCTS:
                edit_inline(call, "❌ Product not found.", kb_products())
                return
            # Esign only if stock > 0
            if PRODUCTS[pkey]["type"] == "request" and get_stock_number(pkey, 365) <= 0:
                edit_inline(call, "❌ Out of stock.", kb_products())
                return
            edit_inline(call, f"{PRODUCTS[pkey]['label']}\nChoose platform:", kb_platforms(pkey))
            return

        if data.startswith("BUY_BACK_PLATFORM|"):
            pkey = data.split("|", 1)[1]
            if pkey not in PRODUCTS:
                edit_inline(call, "❌ Product not found.", kb_products())
                return
            edit_inline(call, f"{PRODUCTS[pkey]['label']}\nChoose platform:", kb_platforms(pkey))
            return

        if data.startswith("BUY_PL|"):
            _, pkey, plat = data.split("|", 2)
            if pkey not in PRODUCTS:
                edit_inline(call, "❌ Product not found.", kb_products())
                return
            edit_inline(call, f"{PRODUCTS[pkey]['label']}\nChoose duration:", kb_durations(pkey, plat))
            return

        if data.startswith("BUY_D|"):
            _, pkey, plat, days = data.split("|", 3)
            days = int(days)
            meta = PRODUCTS.get(pkey)
            if not meta:
                edit_inline(call, "❌ Product not found.", kb_products())
                return

            price = get_price(pkey, days)
            if meta["type"] == "request":
                stock = get_stock_number(pkey, days)
            else:
                stock = count_codes(pkey, days)

            if price is None:
                edit_inline(call, "❌ Price not set.", kb_durations(pkey, plat))
                return
            if stock <= 0:
                edit_inline(call, "❌ Out of stock.", kb_durations(pkey, plat))
                return

            txt = (
                "Confirm purchase?\n\n"
                f"Product: {meta['label']}\n"
                f"Duration: {('365 Days (year)' if (pkey=='ESIGN_CERT' and days==365) else str(days)+' Days')}\n"
                f"Price: {price:.2f}$"
            )
            edit_inline(call, txt, kb_confirm(pkey, plat, days))
            return

        if data.startswith("BUY_OK|"):
            _, pkey, plat, days = data.split("|", 3)
            days = int(days)
            meta = PRODUCTS.get(pkey)
            if not meta:
                edit_inline(call, "❌ Product not found.", kb_products())
                return

            price = get_price(pkey, days)
            if price is None:
                edit_inline(call, "❌ Price not set.", kb_products())
                return

            # check balance
            _, bal, _ = get_user(uid)
            if float(bal) < float(price):
                edit_inline(call, "❌ Not enough balance.", kb_products())
                return

            # REQUEST PRODUCT (Esign): charge balance then ask UDID (no code delivery)
            if meta["type"] == "request":
                if get_stock_number(pkey, days) <= 0:
                    edit_inline(call, "❌ Out of stock.", kb_products())
                    return

                add_balance(uid, -float(price))
                record_sale(uid, "ESIGN_CERT", 365, float(price), "REQUESTED")

                STATE[uid] = {"state": "WAIT_UDID", "product": pkey, "days": days}

                edit_inline(
                    call,
                    "✅ Payment received.\n\n"
                    "Send your UDID DEVICE now.\n"
                    "Contact admin @am_ar_23 if you don't know how to get it.",
                    types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton("⬅ Back", callback_data="BUY_BACK_PRODUCTS")
                    )
                )
                return

            # CODE PRODUCT: pop code and deliver
            code = pop_code(pkey, days)
            if not code:
                edit_inline(call, "❌ Out of stock.", kb_products())
                return

            add_balance(uid, -float(price))
            record_sale(uid, pkey, days, float(price), code)

            done = (
                "✅ Purchase completed!\n\n"
                f"Product: {meta['label']}\n"
                f"Duration: {days} Days\n"
                f"Price: {price:.2f}$\n\n"
                "🔑 CODE:\n"
                f"{code}"
            )
            mk = types.InlineKeyboardMarkup()
            mk.add(types.InlineKeyboardButton("🛍 Buy more", callback_data="BUY_BACK_PRODUCTS"))
            mk.add(types.InlineKeyboardButton("⬅ Back to menu", callback_data="BUY_BACK_MAIN"))
            edit_inline(call, done, mk)
            return

    except Exception as e:
        print("Callback error:", repr(e))
        traceback.print_exc()

# ================= CATCH TEXT (admin paste codes / user UDID) =================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def catch_text(message):
    uid = message.from_user.id
    ensure_user(uid)

    st = STATE.get(uid)
    if not st:
        return

    # admin paste codes
    if st.get("state") == "WAIT_CODES":
        if not is_admin(uid):
            STATE.pop(uid, None)
            return
        product = st["product"]
        days = st["days"]
        lines = message.text.splitlines()
        n = add_stock_codes(product, days, lines)
        STATE.pop(uid, None)
        bot.reply_to(message, f"✅ Added {n} codes to {product} {days} Days.")
        return

    # user UDID for ESIGN
    if st.get("state") == "WAIT_UDID":
        product = st.get("product")
        text = message.text.strip()
        if not text:
            bot.reply_to(message, "❌ Send UDID DEVICE text.")
            return

        # save request
        con = db()
        cur = con.cursor()
        cur.execute("INSERT INTO requests(uid,product,text,created_at) VALUES(?,?,?,?)",
                    (uid, product, text, now_utc()))
        con.commit()
        con.close()

        # forward to admin
        uname = message.from_user.username or ""
        bot.send_message(
            ADMIN_ID,
            f"🧾 ESIGN REQUEST\nUser ID: {uid}\nUsername: @{uname}\n\nUDID DEVICE:\n{text}"
        )

        STATE.pop(uid, None)
        bot.reply_to(
            message,
            "تم إرسال طلبك للمسؤول ,سيتم تفعيل الشهادة على هاتفك\n"
            "تواصل مع المسؤول لتسريع العملية ☜ @am_ar_23"
        )
        return

# ================= RUN =================
def run_forever():
    init_db()
    print("✅ Bot running...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print("Polling crashed:", repr(e))
            traceback.print_exc()
            time.sleep(3)

if __name__ == "__main__":
    run_forever()
