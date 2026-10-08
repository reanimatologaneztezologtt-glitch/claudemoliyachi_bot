"""
💰 Молиявий Трекер Боти — To'xtamurod uchun
Telegram bot bilan to'liq moliyaviy boshqaruv:
- Харажат / Даромад / Қарз
- Нақд / Карта ажратиш
- Категория лимитлари
- Дашборд (ойлик статистика)
- Рўйхат ва CSV экспорт
"""
import os, re, sqlite3, csv, io
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ── Муҳит ────────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
OWNER_ID   = int(os.environ.get("OWNER_ID") or os.environ.get("EGASI_ID") or "0")
DB_PATH    = "moliya.db"

# ── Conversation states ───────────────────────────────────────────────────────
(
    ST_MAIN,
    # Харажат
    ST_EXP_AMOUNT, ST_EXP_METHOD, ST_EXP_CAT, ST_EXP_NOTE,
    # Даромад
    ST_INC_AMOUNT, ST_INC_METHOD, ST_INC_CAT, ST_INC_NOTE,
    # Қарз
    ST_DEBT_DIR, ST_DEBT_PERSON, ST_DEBT_AMOUNT, ST_DEBT_NOTE,
    # Қарз тўлаш
    ST_PAY_DEBT,
    # Созлаш
    ST_SET_KURS, ST_SET_LIMIT, ST_SET_CAT_LIMIT,
    # Маош
    ST_SALARY_AMOUNT, ST_SALARY_METHOD,
) = range(19)

# ── Категориялар ─────────────────────────────────────────────────────────────
CATS_EXP = [
    ("🍽 Озиқ-овқат",     "oziq"),
    ("🚗 Транспорт",      "transport"),
    ("🏠 Уй-жой",         "uy"),
    ("💊 Соғлиқ",         "salomatlik"),
    ("📚 Таълим",         "talim"),
    ("👗 Кийим-кечак",    "kiyim"),
    ("🎮 Ўйин-кулги",     "kulgi"),
    ("📞 Коммуникация",   "kommunikatsiya"),
    ("👨‍👩‍👧 Оила",          "oila"),
    ("💰 Жамғарма",       "jamgarma"),
    ("📦 Бошқа",          "boshqa"),
]
CATS_INC = [
    ("💼 Иш ҳақи",        "maosh"),
    ("📊 Қўшимча иш",     "qoshimcha"),
    ("🏢 Ижара",          "ijara"),
    ("🏆 Мукофот",        "mukofot"),
    ("📦 Бошқа даромад",  "boshqa_inc"),
]
CAT_ICON = {c:label.split()[0] for label,c in CATS_EXP + CATS_INC}
CAT_NAME = {c:label for label,c in CATS_EXP + CATS_INC}

# ── Базавий клавиатура ────────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup([
    ["➕ Харажат", "📥 Даромад"],
    ["🤝 Қарз", "💼 Маош тушди"],
    ["📊 Дашборд", "📋 Рўйхат"],
    ["📑 Ҳисобот", "⚙️ Созлаш"],
], resize_keyboard=True)

# ── Маълумотлар базаси ────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tx (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER, type TEXT, amount REAL,
        currency TEXT DEFAULT 'UZS',
        cat TEXT, method TEXT DEFAULT 'naqd',
        note TEXT, dt TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS debt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER, dir TEXT, person TEXT,
        amount REAL, currency TEXT DEFAULT 'UZS',
        note TEXT, dt TEXT, closed INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cfg (
        uid INTEGER, key TEXT, val TEXT,
        PRIMARY KEY(uid, key)
    )""")
    con.commit(); con.close()

def db_get(uid, key, default=None):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("SELECT val FROM cfg WHERE uid=? AND key=?", (uid, key))
    row = c.fetchone(); con.close()
    return row[0] if row else default

def db_set(uid, key, val):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("INSERT OR REPLACE INTO cfg(uid,key,val) VALUES(?,?,?)", (uid, key, str(val)))
    con.commit(); con.close()

def add_tx(uid, d):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute(
        "INSERT INTO tx(uid,type,amount,currency,cat,method,note,dt) VALUES(?,?,?,?,?,?,?,?)",
        (uid, d["type"], d["amount"], d.get("currency","UZS"),
         d.get("cat","boshqa"), d.get("method","naqd"),
         d.get("note",""), d.get("dt", now_str()))
    )
    txid = c.lastrowid; con.commit(); con.close()
    return txid

def get_tx(uid, period="oy", type_=None):
    since = period_since(period)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row; c = con.cursor()
    if type_:
        c.execute("SELECT * FROM tx WHERE uid=? AND type=? AND dt>=? ORDER BY dt DESC", (uid, type_, since))
    else:
        c.execute("SELECT * FROM tx WHERE uid=? AND dt>=? ORDER BY dt DESC", (uid, since))
    rows = [dict(r) for r in c.fetchall()]; con.close()
    return rows

def del_tx(uid, txid):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("DELETE FROM tx WHERE id=? AND uid=?", (txid, uid))
    ok = c.rowcount > 0; con.commit(); con.close()
    return ok

def add_debt(uid, d):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute(
        "INSERT INTO debt(uid,dir,person,amount,currency,note,dt) VALUES(?,?,?,?,?,?,?)",
        (uid, d["dir"], d["person"], d["amount"],
         d.get("currency","UZS"), d.get("note",""), now_str())
    )
    con.commit(); con.close()

def get_debts(uid, closed=0):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row; c = con.cursor()
    c.execute("SELECT * FROM debt WHERE uid=? AND closed=? ORDER BY dt DESC", (uid, closed))
    rows = [dict(r) for r in c.fetchall()]; con.close()
    return rows

def close_debt(uid, did):
    con = sqlite3.connect(DB_PATH)
    c = con.cursor()
    c.execute("UPDATE debt SET closed=1 WHERE id=? AND uid=?", (did, uid))
    ok = c.rowcount > 0; con.commit(); con.close()
    return ok

# ── Ёрдамчи ──────────────────────────────────────────────────────────────────
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def today():
    return datetime.now().strftime("%Y-%m-%d")

def period_since(period):
    now = datetime.now()
    if period == "kun":    return now.strftime("%Y-%m-%d")
    if period == "hafta":  return (now - timedelta(days=7)).strftime("%Y-%m-%d")
    if period == "oy":     return now.strftime("%Y-%m") + "-01"
    return "2000-01-01"

def get_kurs(uid):
    return float(db_get(uid, "kurs", "12800"))

def to_uzs(amount, currency, uid):
    return amount * get_kurs(uid) if currency == "USD" else amount

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f} млн сўм"
    if n >= 1_000:     return f"{n/1_000:.0f} минг сўм"
    return f"{n:,.0f} сўм"

def fmt_full(n):
    return f"{n:,.0f} сўм"

def is_owner(uid):
    return OWNER_ID == 0 or uid == OWNER_ID

def uzs_parse(text):
    """50000, 50 ming, 1.5 mln, $100, 100 usd"""
    text = text.strip().lower()
    currency = "UZS"
    if re.search(r'\$|usd|dollar', text):
        currency = "USD"
        text = re.sub(r'\$|usd|dollar', '', text).strip()
    m = re.search(r'([\d.,]+)', text)
    if not m: return None, None
    num = float(m.group(1).replace(",", "."))
    rest = text[m.end():].strip()
    if re.search(r'mln|млн|миллион', rest):   num *= 1_000_000
    elif re.search(r'ming|минг|тыс', rest):    num *= 1_000
    return num, currency

def get_limit(uid, cat):
    return float(db_get(uid, f"lim_{cat}", 0) or 0)

def total_limit(uid):
    return float(db_get(uid, "total_limit", 0) or 0)

def progress_bar(pct, width=10):
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    bar = "█" * filled + "░" * (width - filled)
    return bar

# ── Inline клавиатуралар ──────────────────────────────────────────────────────
def method_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💵 Нақд", callback_data="method_naqd"),
        InlineKeyboardButton("💳 Карта", callback_data="method_karta"),
    ]])

def cat_kb(cats):
    buttons = []
    row = []
    for label, code in cats:
        row.append(InlineKeyboardButton(label, callback_data=f"cat_{code}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def period_kb(prefix="period"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Бугун",  callback_data=f"{prefix}_kun"),
        InlineKeyboardButton("📆 Ҳафта",  callback_data=f"{prefix}_hafta"),
        InlineKeyboardButton("🗓 Ой",     callback_data=f"{prefix}_oy"),
        InlineKeyboardButton("📊 Ҳаммаси",callback_data=f"{prefix}_all"),
    ]])

def confirm_kb(yes_data, no_data="cancel"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ҳа", callback_data=yes_data),
        InlineKeyboardButton("❌ Йўқ", callback_data=no_data),
    ]])

# ── /start ────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("⛔ Бу бот фақат шахсий фойдаланиш учун.")
        return
    name = update.effective_user.first_name or "Фойдаланувчи"
    kurs_val = get_kurs(uid)
    text = (
        f"👋 Салом, *{name}*!\n\n"
        f"💰 *Молиявий Трекер* — шахсий бюджет назорати\n\n"
        f"📌 *Имкониятлар:*\n"
        f"• Харажат ва даромадларни қайд этиш\n"
        f"• Нақд / Карта ажратиш\n"
        f"• Категориялар бўйича лимитлар\n"
        f"• Қарзлар назорати\n"
        f"• Ойлик дашборд ва статистика\n"
        f"• CSV экспорт\n\n"
        f"💱 Ҳозирги курс: *1 USD = {kurs_val:,.0f} сўм*\n\n"
        f"Пастдаги тугмалардан фойдаланинг 👇"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KB)
    return ST_MAIN

# ── ХАРАЖАТ ───────────────────────────────────────────────────────────────────
async def exp_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["type"] = "exp"
    await update.message.reply_text(
        "➕ *Харажат миқдорини киритинг:*\n\n"
        "Мисоллар:\n"
        "• `50000` — 50 минг сўм\n"
        "• `1.5 mln` — 1.5 млн сўм\n"
        "• `10 usd` — доллар\n"
        "• `50 ming` — 50 минг",
        parse_mode="Markdown"
    )
    return ST_EXP_AMOUNT

async def exp_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amount, currency = uzs_parse(update.message.text)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Нотўғри рақам. Қайта киритинг:")
        return ST_EXP_AMOUNT
    ctx.user_data["amount"] = amount
    ctx.user_data["currency"] = currency
    disp = f"{amount:,.0f} {'USD' if currency=='USD' else 'сўм'}"
    await update.message.reply_text(
        f"💵 *{disp}* — тўлов усули?",
        parse_mode="Markdown", reply_markup=method_kb()
    )
    return ST_EXP_METHOD

async def exp_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["method"] = "naqd" if "naqd" in q.data else "karta"
    icon = "💵 Нақд" if ctx.user_data["method"] == "naqd" else "💳 Карта"
    await q.edit_message_text(
        f"{icon} — Категорияни танланг:",
        reply_markup=cat_kb(CATS_EXP)
    )
    return ST_EXP_CAT

async def exp_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cat = q.data.replace("cat_", "")
    ctx.user_data["cat"] = cat
    cat_label = CAT_NAME.get(cat, cat)
    uid = q.from_user.id
    lim = get_limit(uid, cat)

    # Лимит огоҳлантириши
    if lim > 0:
        month_txs = get_tx(uid, "oy", "exp")
        cat_spent = sum(to_uzs(t["amount"], t["currency"], uid)
                        for t in month_txs if t["cat"] == cat)
        new_total = cat_spent + to_uzs(
            ctx.user_data["amount"], ctx.user_data["currency"], uid)
        if new_total > lim:
            warn = f"\n⚠️ _Диққат: {cat_label} лимити ({fmt(lim)}) ошади!_"
        else:
            warn = ""
    else:
        warn = ""

    await q.edit_message_text(
        f"{cat_label} — Изоҳ ёзинг (ёки /skip):{warn}",
        parse_mode="Markdown"
    )
    return ST_EXP_NOTE

async def exp_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = "" if update.message.text.strip() in ("/skip","skip","-") else update.message.text.strip()
    ctx.user_data["note"] = note
    uid = update.effective_user.id
    d = ctx.user_data
    uzs = to_uzs(d["amount"], d["currency"], uid)
    cat_label = CAT_NAME.get(d["cat"], d["cat"])
    method_label = "💵 Нақд" if d["method"] == "naqd" else "💳 Карта"
    currency_label = f"{d['amount']:,.0f} {'USD' if d['currency']=='USD' else 'сўм'}"

    text = (
        f"✅ *Тасдиқлаш:*\n\n"
        f"📤 Тури: Харажат\n"
        f"💰 Миқдор: *{currency_label}*"
        + (f" ≈ {fmt(uzs)}" if d["currency"] == "USD" else "") + "\n"
        f"💳 Усул: {method_label}\n"
        f"📁 Категория: {cat_label}\n"
        + (f"📝 Изоҳ: {note}\n" if note else "")
        + f"📅 Сана: {today()}"
    )
    ctx.user_data["preview"] = text
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=confirm_kb("exp_confirm")
    )
    return ST_EXP_NOTE

async def exp_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ Бекор қилинди.")
        return ST_MAIN
    uid = q.from_user.id
    d = ctx.user_data
    txid = add_tx(uid, {
        "type": "exp", "amount": d["amount"], "currency": d["currency"],
        "cat": d["cat"], "method": d["method"], "note": d["note"]
    })
    uzs = to_uzs(d["amount"], d["currency"], uid)

    # Лимит текшириш
    cat = d["cat"]
    lim = get_limit(uid, cat)
    warn = ""
    if lim > 0:
        month_txs = get_tx(uid, "oy", "exp")
        cat_spent = sum(to_uzs(t["amount"], t["currency"], uid)
                        for t in month_txs if t["cat"] == cat)
        pct = cat_spent / lim * 100
        bar = progress_bar(pct)
        warn = f"\n\n📊 {CAT_NAME.get(cat,cat)}: [{bar}] {pct:.0f}%"
        if pct >= 100:
            warn += "\n🔴 *Лимит тўлдирилди!*"
        elif pct >= 80:
            warn += "\n🟡 Лимитга яқинлашдингиз!"

    # Умумий лимит
    tot_lim = total_limit(uid)
    if tot_lim > 0:
        month_exp = sum(to_uzs(t["amount"], t["currency"], uid)
                        for t in get_tx(uid, "oy", "exp"))
        if month_exp >= tot_lim:
            warn += f"\n🔴 *Ойлик умумий лимит ({fmt(tot_lim)}) тўлдирилди!*"

    await q.edit_message_text(
        f"✅ *Харажат қайд этилди!* (#{txid})\n"
        f"📤 {fmt(uzs)} — {CAT_NAME.get(cat,cat)}{warn}",
        parse_mode="Markdown"
    )
    ctx.user_data.clear()
    return ST_MAIN

# ── ДАРОМАД ───────────────────────────────────────────────────────────────────
async def inc_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["type"] = "inc"
    await update.message.reply_text(
        "📥 *Даромад миқдорини киритинг:*\n"
        "Мисол: `500000`, `50 ming`, `100 usd`",
        parse_mode="Markdown"
    )
    return ST_INC_AMOUNT

async def inc_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amount, currency = uzs_parse(update.message.text)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Нотўғри. Қайта киритинг:")
        return ST_INC_AMOUNT
    ctx.user_data["amount"] = amount
    ctx.user_data["currency"] = currency
    disp = f"{amount:,.0f} {'USD' if currency=='USD' else 'сўм'}"
    await update.message.reply_text(
        f"💰 *{disp}* — тўлов усули?",
        parse_mode="Markdown", reply_markup=method_kb()
    )
    return ST_INC_METHOD

async def inc_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["method"] = "naqd" if "naqd" in q.data else "karta"
    await q.edit_message_text("📁 Категорияни танланг:", reply_markup=cat_kb(CATS_INC))
    return ST_INC_CAT

async def inc_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["cat"] = q.data.replace("cat_", "")
    await q.edit_message_text("📝 Изоҳ ёзинг (ёки /skip):")
    return ST_INC_NOTE

async def inc_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = "" if update.message.text.strip() in ("/skip","skip","-") else update.message.text.strip()
    ctx.user_data["note"] = note
    uid = update.effective_user.id
    d = ctx.user_data
    uzs = to_uzs(d["amount"], d["currency"], uid)
    cat_label = CAT_NAME.get(d["cat"], d["cat"])
    method_label = "💵 Нақд" if d["method"] == "naqd" else "💳 Карта"
    text = (
        f"✅ *Тасдиқлаш:*\n\n"
        f"📥 Тури: Даромад\n"
        f"💰 Миқдор: *{d['amount']:,.0f} {'USD' if d['currency']=='USD' else 'сўм'}*"
        + (f" ≈ {fmt(uzs)}" if d["currency"] == "USD" else "") + "\n"
        f"💳 Усул: {method_label}\n"
        f"📁 Категория: {cat_label}\n"
        + (f"📝 Изоҳ: {note}\n" if note else "")
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                     reply_markup=confirm_kb("inc_confirm"))
    return ST_INC_NOTE

async def inc_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ Бекор қилинди.")
        return ST_MAIN
    uid = q.from_user.id
    d = ctx.user_data
    txid = add_tx(uid, {
        "type": "inc", "amount": d["amount"], "currency": d["currency"],
        "cat": d["cat"], "method": d["method"], "note": d["note"]
    })
    uzs = to_uzs(d["amount"], d["currency"], uid)
    await q.edit_message_text(
        f"✅ *Даромад қайд этилди!* (#{txid})\n"
        f"📥 {fmt(uzs)} — {CAT_NAME.get(d['cat'], d['cat'])}",
        parse_mode="Markdown"
    )
    ctx.user_data.clear()
    return ST_MAIN

# ── МАОШ ─────────────────────────────────────────────────────────────────────
async def salary_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["type"] = "inc"
    ctx.user_data["cat"] = "maosh"
    ctx.user_data["note"] = "Иш ҳақи"
    await update.message.reply_text(
        "💼 *Иш ҳақи миқдорини киритинг:*\n"
        "Мисол: `2500000`, `2.5 mln`, `300 usd`",
        parse_mode="Markdown"
    )
    return ST_SALARY_AMOUNT

async def salary_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amount, currency = uzs_parse(update.message.text)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Нотўғри. Қайта киритинг:")
        return ST_SALARY_AMOUNT
    ctx.user_data["amount"] = amount
    ctx.user_data["currency"] = currency
    uid = update.effective_user.id
    uzs = to_uzs(amount, currency, uid)
    disp = f"{amount:,.0f} {'USD' if currency=='USD' else 'сўм'}"
    await update.message.reply_text(
        f"💼 *{disp}*" + (f" ≈ {fmt(uzs)}" if currency=="USD" else "") +
        " — тўлов усули?",
        parse_mode="Markdown", reply_markup=method_kb()
    )
    return ST_SALARY_METHOD

async def salary_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["method"] = "naqd" if "naqd" in q.data else "karta"
    uid = q.from_user.id
    d = ctx.user_data
    uzs = to_uzs(d["amount"], d["currency"], uid)
    txid = add_tx(uid, {
        "type": "inc", "amount": d["amount"], "currency": d["currency"],
        "cat": "maosh", "method": d["method"], "note": "Иш ҳақи"
    })
    await q.edit_message_text(
        f"💼 *Иш ҳақи қайд этилди!* (#{txid})\n"
        f"📥 {fmt(uzs)} — {'💵 Нақд' if d['method']=='naqd' else '💳 Карта'}",
        parse_mode="Markdown"
    )
    ctx.user_data.clear()
    return ST_MAIN

# ── ҚАРЗ ─────────────────────────────────────────────────────────────────────
async def debt_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🤝 *Қарз тури:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💸 Бердим (қарзга)", callback_data="debt_dir_give"),
            InlineKeyboardButton("💰 Олдим (қарзга)", callback_data="debt_dir_take"),
        ]])
    )
    return ST_DEBT_DIR

async def debt_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["dir"] = "give" if "give" in q.data else "take"
    label = "💸 Бердим" if ctx.user_data["dir"] == "give" else "💰 Олдим"
    await q.edit_message_text(f"{label} — Кимга/Кимдан (исм):")
    return ST_DEBT_PERSON

async def debt_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["person"] = update.message.text.strip()
    await update.message.reply_text(
        "💰 *Миқдорни киритинг:*\n"
        "Мисол: `500000`, `50 usd`",
        parse_mode="Markdown"
    )
    return ST_DEBT_AMOUNT

async def debt_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amount, currency = uzs_parse(update.message.text)
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Нотўғри. Қайта:")
        return ST_DEBT_AMOUNT
    ctx.user_data["amount"] = amount
    ctx.user_data["currency"] = currency
    await update.message.reply_text("📝 Изоҳ (ёки /skip):")
    return ST_DEBT_NOTE

async def debt_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    note = "" if update.message.text.strip() in ("/skip","skip","-") else update.message.text.strip()
    ctx.user_data["note"] = note
    uid = update.effective_user.id
    d = ctx.user_data
    uzs = to_uzs(d["amount"], d["currency"], uid)
    dir_label = "💸 Бердим (қарзга)" if d["dir"] == "give" else "💰 Олдим (қарзга)"
    text = (
        f"✅ *Тасдиқлаш:*\n\n"
        f"🤝 {dir_label}\n"
        f"👤 Шахс: *{d['person']}*\n"
        f"💰 Миқдор: *{d['amount']:,.0f} {'USD' if d['currency']=='USD' else 'сўм'}*"
        + (f" ≈ {fmt(uzs)}" if d["currency"]=="USD" else "") + "\n"
        + (f"📝 Изоҳ: {note}" if note else "")
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                     reply_markup=confirm_kb("debt_confirm"))
    return ST_DEBT_NOTE

async def debt_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ Бекор қилинди.")
        return ST_MAIN
    uid = q.from_user.id
    d = ctx.user_data
    add_debt(uid, d)
    uzs = to_uzs(d["amount"], d["currency"], uid)
    dir_label = "💸 Берилди" if d["dir"] == "give" else "💰 Олинди"
    await q.edit_message_text(
        f"✅ *Қарз қайд этилди!*\n"
        f"{dir_label}: {fmt(uzs)} — {d['person']}",
        parse_mode="Markdown"
    )
    ctx.user_data.clear()
    return ST_MAIN

# ── ДАШБОРД ───────────────────────────────────────────────────────────────────
async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = get_tx(uid, "oy")
    now = datetime.now()

    inc = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc")
    exp = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp")
    naqd_exp = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp" and t["method"]=="naqd")
    karta_exp = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp" and t["method"]=="karta")
    naqd_inc = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc" and t["method"]=="naqd")
    karta_inc = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc" and t["method"]=="karta")
    balance = inc - exp

    # Категориялар бўйича харажат
    cat_exp = {}
    for t in txs:
        if t["type"] == "exp":
            cat_exp[t["cat"]] = cat_exp.get(t["cat"], 0) + to_uzs(t["amount"],t["currency"],uid)
    cat_rows = sorted(cat_exp.items(), key=lambda x: -x[1])

    # Лимит текшириш
    tot_lim = total_limit(uid)
    limit_line = ""
    if tot_lim > 0:
        pct = min(exp / tot_lim * 100, 100)
        bar = progress_bar(pct)
        status = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🟢"
        limit_line = f"\n{status} Лимит: [{bar}] {pct:.0f}% ({fmt(exp)}/{fmt(tot_lim)})"

    # Активе қарзлар
    debts = get_debts(uid, 0)
    give_total = sum(to_uzs(d["amount"],d["currency"],uid) for d in debts if d["dir"]=="give")
    take_total = sum(to_uzs(d["amount"],d["currency"],uid) for d in debts if d["dir"]=="take")

    lines = [
        f"📊 *{now.strftime('%B %Y')} — Дашборд*\n",
        f"📥 *Даромад:* {fmt(inc)}",
        f"  └ 💵 Нақд: {fmt(naqd_inc)}",
        f"  └ 💳 Карта: {fmt(karta_inc)}",
        f"\n📤 *Харажат:* {fmt(exp)}",
        f"  └ 💵 Нақд: {fmt(naqd_exp)}",
        f"  └ 💳 Карта: {fmt(karta_exp)}",
        f"\n⚖️ *Баланс:* {'✅' if balance>=0 else '❌'} {fmt(abs(balance))} {'(ортиқча)' if balance>=0 else '(камомад)'}",
        limit_line if limit_line else "",
    ]

    if cat_rows:
        lines.append("\n📁 *Категориялар (ой):*")
        for cat, val in cat_rows[:6]:
            icon = CAT_ICON.get(cat, "📦")
            lim = get_limit(uid, cat)
            lim_str = f" / {fmt(lim)}" if lim else ""
            pct_str = f" {val/lim*100:.0f}%{'🔴' if val>lim else ''}" if lim else ""
            lines.append(f"  {icon} {CAT_NAME.get(cat,cat)}: {fmt(val)}{lim_str}{pct_str}")

    if debts:
        lines.append(f"\n🤝 *Қарзлар:*")
        if give_total: lines.append(f"  💸 Берилган: {fmt(give_total)}")
        if take_total: lines.append(f"  💰 Олинган: {fmt(take_total)}")

    # Охирги 3 та операция
    recent = get_tx(uid)[:3]
    if recent:
        lines.append("\n🕐 *Охирги операциялар:*")
        for t in recent:
            uzs = to_uzs(t["amount"], t["currency"], uid)
            sign = "📥" if t["type"]=="inc" else "📤" if t["type"]=="exp" else "🤝"
            icon = CAT_ICON.get(t["cat"], "📦")
            method = "💵" if t["method"]=="naqd" else "💳"
            note_str = f" ({t['note']})" if t.get("note") else ""
            lines.append(f"  {sign}{icon} {fmt(uzs)} {method}{note_str}")

    await update.message.reply_text(
        "\n".join(l for l in lines if l),
        parse_mode="Markdown"
    )
    return ST_MAIN

# ── РЎЙХАТ ───────────────────────────────────────────────────────────────────
async def list_txs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Қайси давр?*", parse_mode="Markdown",
        reply_markup=period_kb("list")
    )
    return ST_MAIN

async def list_period_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    period = q.data.replace("list_", "")
    txs = get_tx(uid, period)

    if not txs:
        await q.edit_message_text("📭 Операциялар топилмади.")
        return ST_MAIN

    period_labels = {"kun":"Бугун","hafta":"Ҳафта","oy":"Жорий ой","all":"Барчаси"}
    lines = [f"📋 *{period_labels.get(period,'Рўйхат')}* ({len(txs)} та)\n"]

    for t in txs[:20]:
        uzs = to_uzs(t["amount"], t["currency"], uid)
        sign = "📥" if t["type"]=="inc" else "📤" if t["type"]=="exp" else "🤝"
        icon = CAT_ICON.get(t["cat"], "📦")
        method = "💵" if t["method"]=="naqd" else ("💳" if t["method"]=="karta" else "")
        dt = t["dt"][:10]
        note_str = f" _{t['note']}_" if t.get("note") else ""
        lines.append(f"`#{t['id']}` {sign}{icon} *{fmt(uzs)}* {method} {dt}{note_str}")

    if len(txs) > 20:
        lines.append(f"\n_...ва яна {len(txs)-20} та. CSV юклаш учун /export_")

    # Якунлар
    inc = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc")
    exp = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp")
    lines.append(f"\n📥 Жами даромад: *{fmt(inc)}*")
    lines.append(f"📤 Жами харажат: *{fmt(exp)}*")
    lines.append(f"⚖️ Баланс: *{fmt(abs(inc-exp))}* {'✅' if inc>=exp else '❌'}")

    # Ўчириш тугмалари (охирги 5 та учун)
    del_buttons = []
    for t in txs[:5]:
        del_buttons.append(InlineKeyboardButton(
            f"🗑 #{t['id']}", callback_data=f"deltx_{t['id']}"
        ))
    kb = []
    for i in range(0, len(del_buttons), 3):
        kb.append(del_buttons[i:i+3])
    kb.append([InlineKeyboardButton("📥 CSV экспорт", callback_data=f"export_{period}")])

    await q.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return ST_MAIN

async def delete_tx_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    txid = int(q.data.replace("deltx_", ""))
    if del_tx(uid, txid):
        await q.answer(f"✅ #{txid} ўчирилди", show_alert=True)
        await q.edit_message_text(f"🗑 *#{txid} операция ўчирилди.*", parse_mode="Markdown")
    else:
        await q.answer("❌ Топилмади", show_alert=True)
    return ST_MAIN

# ── ҲИСОБОТ ───────────────────────────────────────────────────────────────────
async def report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📑 *Ҳисобот даври:*", parse_mode="Markdown",
        reply_markup=period_kb("rep")
    )
    return ST_MAIN

async def report_period_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    period = q.data.replace("rep_", "")
    txs = get_tx(uid, period)

    period_labels = {"kun":"Бугун","hafta":"Ҳафта","oy":"Жорий ой","all":"Барчаси"}
    label = period_labels.get(period, period)

    inc_naqd = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc" and t["method"]=="naqd")
    inc_karta= sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="inc" and t["method"]=="karta")
    exp_naqd = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp" and t["method"]=="naqd")
    exp_karta= sum(to_uzs(t["amount"],t["currency"],uid) for t in txs if t["type"]=="exp" and t["method"]=="karta")
    total_inc = inc_naqd + inc_karta
    total_exp = exp_naqd + exp_karta
    balance = total_inc - total_exp

    # Категориялар
    cat_naqd = {}; cat_karta = {}
    for t in txs:
        if t["type"] == "exp":
            uzs = to_uzs(t["amount"],t["currency"],uid)
            if t["method"] == "naqd":
                cat_naqd[t["cat"]] = cat_naqd.get(t["cat"],0) + uzs
            else:
                cat_karta[t["cat"]] = cat_karta.get(t["cat"],0) + uzs

    all_cats = set(list(cat_naqd.keys()) + list(cat_karta.keys()))

    lines = [
        f"📑 *Якуний ҳисобот — {label}*\n",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📥 *ДАРОМАДЛАР*",
        f"  💵 Нақд:  {fmt_full(inc_naqd)}",
        f"  💳 Карта: {fmt_full(inc_karta)}",
        f"  📊 Жами:  *{fmt_full(total_inc)}*",
        f"",
        f"📤 *ХАРАЖАТЛАР*",
        f"  💵 Нақд:  {fmt_full(exp_naqd)}",
        f"  💳 Карта: {fmt_full(exp_karta)}",
        f"  📊 Жами:  *{fmt_full(total_exp)}*",
    ]

    if all_cats:
        lines.append(f"")
        lines.append(f"📁 *Категориялар бўйича:*")
        sorted_cats = sorted(all_cats,
            key=lambda c: -(cat_naqd.get(c,0)+cat_karta.get(c,0)))
        for cat in sorted_cats:
            n = cat_naqd.get(cat,0); k = cat_karta.get(cat,0)
            icon = CAT_ICON.get(cat,"📦")
            name = CAT_NAME.get(cat,cat)
            lines.append(f"  {icon} {name}")
            if n: lines.append(f"    💵 {fmt_full(n)}")
            if k: lines.append(f"    💳 {fmt_full(k)}")
            lines.append(f"    📊 Жами: {fmt_full(n+k)}")

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"⚖️ *ЯКУНИЙ БАЛАНС*",
        f"  ✅ Даромад: {fmt_full(total_inc)}",
        f"  ❌ Харажат: {fmt_full(total_exp)}",
        f"  {'💚' if balance>=0 else '❗'} {'Тежалган' if balance>=0 else 'Камомад'}: *{fmt_full(abs(balance))}*",
    ]

    if total_inc > 0:
        savings_pct = (balance/total_inc*100) if balance > 0 else 0
        lines.append(f"  📈 Тежаш %: *{savings_pct:.1f}%*")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📥 CSV юклаш", callback_data=f"export_{period}")
        ]])
    )
    return ST_MAIN

# ── CSV ЭКСПОРТ ───────────────────────────────────────────────────────────────
async def export_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("📥 Тайёрланмоқда...")
    uid = q.from_user.id
    period = q.data.replace("export_", "")
    txs = get_tx(uid, period)

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(["#", "Сана", "Тури", "Усул", "Категория", "Миқдор", "Валюта", "Сўмда", "Изоҳ"])
    for t in txs:
        uzs = to_uzs(t["amount"], t["currency"], uid)
        type_label = {"exp":"Харажат","inc":"Даромад"}.get(t["type"], t["type"])
        method_label = {"naqd":"Нақд","karta":"Карта"}.get(t["method"],"")
        writer.writerow([
            t["id"], t["dt"][:10], type_label,
            method_label, CAT_NAME.get(t["cat"],t["cat"]),
            t["amount"], t["currency"], f"{uzs:.0f}", t.get("note","")
        ])

    period_labels = {"kun":"bugun","hafta":"hafta","oy":"oy","all":"hammasi"}
    filename = f"moliyaviy_{period_labels.get(period,period)}_{today()}.csv"

    buf.seek(0)
    await q.message.reply_document(
        document=buf.read().encode("utf-8-sig"),
        filename=filename,
        caption=f"📥 *{filename}*\n{len(txs)} та операция",
        parse_mode="Markdown"
    )
    return ST_MAIN

async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = get_tx(uid, "all")
    if not txs:
        await update.message.reply_text("📭 Маълумот йўқ.")
        return ST_MAIN

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["#", "Сана", "Тури", "Усул", "Категория", "Миқдор", "Валюта", "Сўмда", "Изоҳ"])
    for t in txs:
        uzs = to_uzs(t["amount"], t["currency"], uid)
        type_label = {"exp":"Харажат","inc":"Даромад"}.get(t["type"], t["type"])
        method_label = {"naqd":"Нақд","karta":"Карта"}.get(t["method"],"")
        writer.writerow([
            t["id"], t["dt"][:10], type_label,
            method_label, CAT_NAME.get(t["cat"],t["cat"]),
            t["amount"], t["currency"], f"{uzs:.0f}", t.get("note","")
        ])

    filename = f"moliyaviy_barchasi_{today()}.csv"
    buf.seek(0)
    await update.message.reply_document(
        document=buf.read().encode("utf-8-sig"),
        filename=filename,
        caption=f"📥 *{filename}*\n{len(txs)} та операция",
        parse_mode="Markdown"
    )
    return ST_MAIN

# ── ҚАРЗЛАР ───────────────────────────────────────────────────────────────────
async def debts_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    debts = get_debts(uid, 0)

    if not debts:
        await update.message.reply_text("🤝 Актив қарзлар йўқ.")
        return ST_MAIN

    give_total = sum(to_uzs(d["amount"],d["currency"],uid) for d in debts if d["dir"]=="give")
    take_total = sum(to_uzs(d["amount"],d["currency"],uid) for d in debts if d["dir"]=="take")

    lines = [f"🤝 *Қарзлар рўйхати*\n"]
    lines.append(f"💸 Берилган: *{fmt(give_total)}*")
    lines.append(f"💰 Олинган: *{fmt(take_total)}*\n")

    buttons = []
    for d in debts:
        uzs = to_uzs(d["amount"],d["currency"],uid)
        dir_icon = "💸" if d["dir"]=="give" else "💰"
        lines.append(f"`#{d['id']}` {dir_icon} *{fmt(uzs)}* — {d['person']}")
        if d.get("note"): lines.append(f"  _{d['note']}_")
        lines.append(f"  📅 {d['dt'][:10]}")
        buttons.append([InlineKeyboardButton(
            f"✅ #{d['id']} тўланди", callback_data=f"debt_close_{d['id']}"
        )])

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_MAIN

async def debt_close_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    did = int(q.data.replace("debt_close_", ""))
    if close_debt(uid, did):
        await q.edit_message_text(f"✅ *Қарз #{did} ёпилди!*", parse_mode="Markdown")
    else:
        await q.answer("❌ Топилмади", show_alert=True)
    return ST_MAIN

# ── СОЗЛАШ ────────────────────────────────────────────────────────────────────
async def settings_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kurs_val = get_kurs(uid)
    tot_lim = total_limit(uid)
    lines = [
        "⚙️ *Созлаш*\n",
        f"💱 Валюта курси: *1 USD = {kurs_val:,.0f} сўм*",
        f"⚠️ Ойлик умумий лимит: *{fmt(tot_lim) if tot_lim else 'белгиланмаган'}*",
        "\nНима ўзгартирасиз?"
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Курс ўзгартириш", callback_data="set_kurs")],
        [InlineKeyboardButton("⚠️ Умумий лимит", callback_data="set_total_limit")],
        [InlineKeyboardButton("📁 Категория лимитлари", callback_data="set_cat_limits")],
    ])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
    return ST_MAIN

async def set_kurs_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur = get_kurs(uid)
    await q.edit_message_text(
        f"💱 Ҳозирги курс: *1 USD = {cur:,.0f} сўм*\n\nЯнги курсни киритинг:",
        parse_mode="Markdown"
    )
    ctx.user_data["action"] = "set_kurs"
    return ST_SET_KURS

async def set_kurs_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        val = float(update.message.text.strip().replace(",",".").replace(" ",""))
        if val < 1000 or val > 99999:
            raise ValueError
    except:
        await update.message.reply_text("❌ Нотўғри. Мисол: `12800`", parse_mode="Markdown")
        return ST_SET_KURS
    db_set(uid, "kurs", val)
    await update.message.reply_text(
        f"✅ *Курс сақланди:* 1 USD = {val:,.0f} сўм", parse_mode="Markdown",
        reply_markup=MAIN_KB
    )
    return ST_MAIN

async def set_total_limit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur = total_limit(uid)
    await q.edit_message_text(
        f"⚠️ Ҳозирги лимит: *{fmt(cur) if cur else 'белгиланмаган'}*\n\n"
        f"Янги ойлик умумий харажат лимитини киритинг:\n"
        f"Мисол: `5000000`, `5 mln`\n"
        f"(0 киритсангиз — лимит олиб ташланади)",
        parse_mode="Markdown"
    )
    ctx.user_data["action"] = "set_total_limit"
    return ST_SET_LIMIT

async def set_limit_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    amount, _ = uzs_parse(update.message.text)
    if amount is None:
        await update.message.reply_text("❌ Нотўғри миқдор.")
        return ST_SET_LIMIT
    db_set(uid, "total_limit", amount)
    if amount == 0:
        await update.message.reply_text("✅ Умумий лимит олиб ташланди.", reply_markup=MAIN_KB)
    else:
        await update.message.reply_text(
            f"✅ *Ойлик лимит белгиланди:* {fmt(amount)}", parse_mode="Markdown",
            reply_markup=MAIN_KB
        )
    return ST_MAIN

async def set_cat_limits_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    buttons = []
    for label, code in CATS_EXP:
        lim = get_limit(uid, code)
        lim_str = f" ({fmt(lim)})" if lim else ""
        buttons.append([InlineKeyboardButton(f"{label}{lim_str}", callback_data=f"setlim_{code}")])
    await q.edit_message_text(
        "📁 *Категория лимитларини белгиланг:*\nҚайсини ўзгартирасиз?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_MAIN

async def set_cat_lim_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cat = q.data.replace("setlim_", "")
    ctx.user_data["lim_cat"] = cat
    uid = q.from_user.id
    cur = get_limit(uid, cat)
    name = CAT_NAME.get(cat, cat)
    await q.edit_message_text(
        f"📁 *{name}*\n"
        f"Ҳозирги лимит: *{fmt(cur) if cur else 'йўқ'}*\n\n"
        f"Янги лимит киритинг (0 = ўчириш):",
        parse_mode="Markdown"
    )
    return ST_SET_CAT_LIMIT

async def set_cat_lim_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cat = ctx.user_data.get("lim_cat")
    if not cat:
        await update.message.reply_text("❌ Хато. Қайтадан /start", reply_markup=MAIN_KB)
        return ST_MAIN
    amount, _ = uzs_parse(update.message.text)
    if amount is None:
        await update.message.reply_text("❌ Нотўғри миқдор.")
        return ST_SET_CAT_LIMIT
    if amount == 0:
        db_set(uid, f"lim_{cat}", 0)
        await update.message.reply_text(
            f"✅ *{CAT_NAME.get(cat,cat)}* лимити олиб ташланди.",
            parse_mode="Markdown", reply_markup=MAIN_KB
        )
    else:
        db_set(uid, f"lim_{cat}", amount)
        await update.message.reply_text(
            f"✅ *{CAT_NAME.get(cat,cat)}* лимити: *{fmt(amount)}*",
            parse_mode="Markdown", reply_markup=MAIN_KB
        )
    ctx.user_data.pop("lim_cat", None)
    return ST_MAIN

# ── ТАВСИЯ ────────────────────────────────────────────────────────────────────
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Тафсилли статистика"""
    uid = update.effective_user.id

    # Сўнгги 3 ой
    lines = ["📈 *3 ойлик статистика*\n"]
    now = datetime.now()
    for i in range(3, 0, -1):
        m = now.month - i
        y = now.year
        if m <= 0: m += 12; y -= 1
        since = f"{y}-{m:02d}-01"
        if m == 12: end_y, end_m = y+1, 1
        else: end_y, end_m = y, m+1
        end = f"{end_y}-{end_m:02d}-01"

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row; c = con.cursor()
        c.execute("SELECT * FROM tx WHERE uid=? AND dt>=? AND dt<? ORDER BY dt DESC",
                  (uid, since, end))
        month_txs = [dict(r) for r in c.fetchall()]; con.close()

        inc = sum(to_uzs(t["amount"],t["currency"],uid) for t in month_txs if t["type"]=="inc")
        exp = sum(to_uzs(t["amount"],t["currency"],uid) for t in month_txs if t["type"]=="exp")
        bal = inc - exp
        month_name = datetime(y,m,1).strftime("%B")
        lines.append(f"📅 *{month_name} {y}*")
        lines.append(f"  📥 {fmt(inc)} | 📤 {fmt(exp)} | {'✅' if bal>=0 else '❌'} {fmt(abs(bal))}")

    # Жорий ой категориялар
    txs = get_tx(uid, "oy", "exp")
    cat_exp = {}
    for t in txs:
        uzs = to_uzs(t["amount"],t["currency"],uid)
        cat_exp[t["cat"]] = cat_exp.get(t["cat"],0)+uzs
    if cat_exp:
        lines.append(f"\n📁 *Жорий ой — нақд/карта:*")
        for cat, val in sorted(cat_exp.items(), key=lambda x:-x[1]):
            naqd = sum(to_uzs(t["amount"],t["currency"],uid) for t in txs
                       if t["cat"]==cat and t["method"]=="naqd")
            karta = val - naqd
            icon = CAT_ICON.get(cat,"📦")
            name = CAT_NAME.get(cat,cat)
            lines.append(f"  {icon} {name}: {fmt(val)}")
            if naqd: lines.append(f"    💵 {fmt(naqd)}")
            if karta: lines.append(f"    💳 {fmt(karta)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    return ST_MAIN

# ── АСОСИЙ ХАБАР ЙЎРУТУВЧИ ───────────────────────────────────────────────────
async def main_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    if not is_owner(uid): return

    if text == "➕ Харажат":   return await exp_start(update, ctx)
    if text == "📥 Даромад":   return await inc_start(update, ctx)
    if text == "🤝 Қарз":      return await debt_start(update, ctx)
    if text == "💼 Маош тушди":return await salary_start(update, ctx)
    if text == "📊 Дашборд":   return await dashboard(update, ctx)
    if text == "📋 Рўйхат":    return await list_txs(update, ctx)
    if text == "📑 Ҳисобот":   return await report(update, ctx)
    if text == "⚙️ Созлаш":    return await settings_menu(update, ctx)
    return ST_MAIN

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Бекор қилинди.", reply_markup=MAIN_KB)
    return ST_MAIN

# ── АСОСИЙ ───────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_message),
        ],
        states={
            ST_MAIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_message),
                CallbackQueryHandler(list_period_cb, pattern="^list_"),
                CallbackQueryHandler(report_period_cb, pattern="^rep_"),
                CallbackQueryHandler(export_cb, pattern="^export_"),
                CallbackQueryHandler(delete_tx_cb, pattern="^deltx_"),
                CallbackQueryHandler(debt_close_cb, pattern="^debt_close_"),
                CallbackQueryHandler(set_kurs_cb, pattern="^set_kurs$"),
                CallbackQueryHandler(set_total_limit_cb, pattern="^set_total_limit$"),
                CallbackQueryHandler(set_cat_limits_cb, pattern="^set_cat_limits$"),
                CallbackQueryHandler(set_cat_lim_select, pattern="^setlim_"),
                CallbackQueryHandler(inc_confirm, pattern="^inc_confirm$"),
                CallbackQueryHandler(debt_confirm, pattern="^debt_confirm$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            ST_EXP_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, exp_amount)],
            ST_EXP_METHOD:  [CallbackQueryHandler(exp_method, pattern="^method_")],
            ST_EXP_CAT:     [CallbackQueryHandler(exp_cat, pattern="^cat_")],
            ST_EXP_NOTE:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, exp_note),
                CallbackQueryHandler(exp_confirm, pattern="^exp_confirm$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            ST_INC_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, inc_amount)],
            ST_INC_METHOD:  [CallbackQueryHandler(inc_method, pattern="^method_")],
            ST_INC_CAT:     [CallbackQueryHandler(inc_cat, pattern="^cat_")],
            ST_INC_NOTE:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, inc_note),
                CallbackQueryHandler(inc_confirm, pattern="^inc_confirm$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            ST_DEBT_DIR:    [CallbackQueryHandler(debt_dir, pattern="^debt_dir_")],
            ST_DEBT_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, debt_person)],
            ST_DEBT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, debt_amount)],
            ST_DEBT_NOTE:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, debt_note),
                CallbackQueryHandler(debt_confirm, pattern="^debt_confirm$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            ST_SALARY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, salary_amount)],
            ST_SALARY_METHOD: [CallbackQueryHandler(salary_method, pattern="^method_")],
            ST_SET_KURS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, set_kurs_input)],
            ST_SET_LIMIT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, set_limit_input)],
            ST_SET_CAT_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_cat_lim_input)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("stats", cmd_stats))

    print("🤖 Молиявий Трекер боти ишга тушди...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
