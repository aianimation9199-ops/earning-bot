import telebot
from telebot import types
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import datetime

# ─── Configuration ────────────────────────────────────────────────────────────
API_TOKEN  = os.getenv('BOT_TOKEN')
MONGO_URI  = os.getenv('MONGO_URI')
ADMIN_ID   = int(os.getenv('ADMIN_ID', '0'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '')
GROUP_ID   = os.getenv('GROUP_ID', '')

# ── Startup check ──
print("=" * 50)
print(f"BOT_TOKEN set: {'✅ YES' if API_TOKEN else '❌ NO - Bot nahi chalega!'}")
print(f"MONGO_URI set: {'✅ YES' if MONGO_URI else '❌ NO'}")
print(f"ADMIN_ID: {ADMIN_ID}")
print(f"CHANNEL_ID: {CHANNEL_ID}")
print(f"GROUP_ID: {GROUP_ID}")
print("=" * 50)

if not API_TOKEN:
    raise ValueError("BOT_TOKEN environment variable set nahi hai!")

bot    = telebot.TeleBot(API_TOKEN, parse_mode=None)
client = MongoClient(MONGO_URI)
db     = client['earning_db']
col    = db['platforms']
polls_col  = db['polls']
users_col  = db['users']    # user tracking ke liye

user_data: dict = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def track_user(user):
    """User ko DB mein track karo"""
    try:
        users_col.update_one(
            {"user_id": user.id},
            {"$set": {
                "user_id":    user.id,
                "username":   user.username or "",
                "first_name": user.first_name or "",
                "last_seen":  datetime.datetime.utcnow()
            },
            "$setOnInsert": {"joined": datetime.datetime.utcnow()}},
            upsert=True
        )
    except Exception:
        pass

def check_membership(user_id: int) -> bool:
    if not CHANNEL_ID or not GROUP_ID:
        return True
    try:
        for chat in (CHANNEL_ID, GROUP_ID):
            status = bot.get_chat_member(chat, user_id).status
            if status in ('left', 'kicked'):
                return False
        return True
    except Exception:
        return True

def force_join_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    if CHANNEL_ID:
        markup.add(types.InlineKeyboardButton(
            "📢 Join Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    if GROUP_ID:
        markup.add(types.InlineKeyboardButton(
            "💬 Join Group", url=f"https://t.me/{GROUP_ID.lstrip('@')}"))
    markup.add(types.InlineKeyboardButton(
        "✅ Join कर लिया – Continue", callback_data="check_join"))
    return markup

# ─── /start ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    track_user(message.from_user)

    if not check_membership(uid) and not is_admin(uid):
        bot.send_message(
            uid,
            "⚠️ *Access के लिए पहले Join करें:*\n\n"
            "Channel और Group दोनों join करें, तभी bot use होगा।",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return
    _show_main_menu(uid, message.from_user.first_name)

def _show_main_menu(chat_id: int, first_name: str):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🚀 सभी Earning Platforms देखें", callback_data="view_links")
    )

    if chat_id == ADMIN_ID:
        markup.add(
            types.InlineKeyboardButton("➕ नया Platform Add करें",   callback_data="admin_add"),
            types.InlineKeyboardButton("🗑️ Platform Delete करें",    callback_data="admin_delete"),
            types.InlineKeyboardButton("📊 Stats & Analytics",       callback_data="admin_stats"),
            types.InlineKeyboardButton("📣 Poll भेजें",              callback_data="admin_poll"),
            types.InlineKeyboardButton("📈 Poll Results देखें",      callback_data="poll_results"),
            types.InlineKeyboardButton("🔧 System Diagnostics",      callback_data="diagnostics"),
        )

    bot.send_message(
        chat_id,
        f"👋 नमस्ते *{first_name}*!\n\n"
        f"💸 *Earning Bot* में आपका स्वागत है।\n"
        f"नीचे से काम चुनें 👇",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ─── Force Join ───────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "check_join")
def recheck_join(call):
    uid = call.from_user.id
    track_user(call.from_user)
    if check_membership(uid):
        bot.answer_callback_query(call.id, "✅ Verified! Welcome!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        _show_main_menu(uid, call.from_user.first_name)
    else:
        bot.answer_callback_query(call.id, "❌ अभी join नहीं किया।", show_alert=True)

# ─── Diagnostics (Admin) ──────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "diagnostics")
def diagnostics(call):
    if not is_admin(call.from_user.id): return

    results = []

    # 1. Bot token check
    try:
        me = bot.get_me()
        results.append(f"🤖 Bot: @{me.username} ✅")
    except Exception as e:
        results.append(f"🤖 Bot Token: ❌ {e}")

    # 2. MongoDB check
    try:
        client.admin.command('ping')
        p_count = col.count_documents({})
        u_count = users_col.count_documents({})
        results.append(f"🍃 MongoDB: ✅ Connected")
        results.append(f"📦 Platforms: {p_count}")
        results.append(f"👥 Total Users: {u_count}")
    except Exception as e:
        results.append(f"🍃 MongoDB: ❌ {e}")

    # 3. Channel check
    try:
        ch = bot.get_chat(CHANNEL_ID)
        results.append(f"📢 Channel: @{ch.username or ch.title} ✅")
    except Exception as e:
        results.append(f"📢 Channel ({CHANNEL_ID}): ❌ {e}")

    # 4. Group check
    try:
        gr = bot.get_chat(GROUP_ID)
        results.append(f"💬 Group: {gr.title} ✅")
    except Exception as e:
        results.append(f"💬 Group ({GROUP_ID}): ❌ {e}")

    # 5. Admin check
    results.append(f"👑 Admin ID: {ADMIN_ID} ✅")

    text = "🔧 *System Diagnostics*\n\n" + "\n".join(results)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                          reply_markup=markup, parse_mode="Markdown")

# ─── Stats (Admin) ────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def admin_stats(call):
    if not is_admin(call.from_user.id): return

    total_users    = users_col.count_documents({})
    total_platforms = col.count_documents({})
    total_polls    = polls_col.count_documents({})

    # Last 24h active users
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    active_24h = users_col.count_documents({"last_seen": {"$gte": since}})

    # Last 7 days
    since_7d = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    active_7d = users_col.count_documents({"last_seen": {"$gte": since_7d}})

    text = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 *Total Users:* {total_users}\n"
        f"🟢 *Active (24h):* {active_24h}\n"
        f"📅 *Active (7 days):* {active_7d}\n\n"
        f"📦 *Total Platforms:* {total_platforms}\n"
        f"📣 *Total Polls:* {total_polls}\n\n"
        f"🕐 *Updated:* Just now"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("👥 All Users List", callback_data="users_list"),
        types.InlineKeyboardButton("🔙 Back",           callback_data="back_main")
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                          reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "users_list")
def users_list(call):
    if not is_admin(call.from_user.id): return
    users = list(users_col.find().sort("last_seen", -1).limit(20))
    if not users:
        bot.answer_callback_query(call.id, "कोई user नहीं।", show_alert=True)
        return

    lines = ["👥 *Recent Users (last 20):*\n"]
    for i, u in enumerate(users, 1):
        uname = f"@{u['username']}" if u.get('username') else u.get('first_name', 'Unknown')
        uid_str = u['user_id']
        lines.append(f"{i}. {uname} (`{uid_str}`)")

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_stats"))
    bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id,
                          reply_markup=markup, parse_mode="Markdown")

# ─── Admin Count ──────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_count")
def admin_count(call):
    if not is_admin(call.from_user.id): return
    n = col.count_documents({})
    bot.answer_callback_query(call.id, f"📊 Total Platforms: {n}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN: POLL
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "admin_poll")
def start_poll(call):
    if not is_admin(call.from_user.id): return
    uid = call.from_user.id
    user_data[uid] = {'action': 'poll'}
    msg = bot.send_message(uid,
        "📣 *नया Poll बनाएं*\n\n"
        "Poll का *Question* भेजें:\n"
        "_(e.g. क्या यह नया Earning Platform लाना चाहिए?)_",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _poll_question)

def _poll_question(message):
    uid = message.from_user.id
    if user_data.get(uid, {}).get('action') != 'poll': return
    question = message.text.strip()
    user_data[uid]['question'] = question

    sent_polls = {}
    errors = []

    for chat_id, chat_name in [(CHANNEL_ID, "Channel"), (GROUP_ID, "Group")]:
        try:
            sent = bot.send_poll(
                chat_id,
                question=question,
                options=["✅ हाँ, लाओ!", "❌ नहीं चाहिए"],
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=86400
            )
            sent_polls[chat_name] = {
                "chat_id":    chat_id,
                "message_id": sent.message_id,
                "poll_id":    sent.poll.id
            }
        except Exception as e:
            errors.append(f"⚠️ {chat_name}: {e}")

    doc = {
        "question":  question,
        "polls":     sent_polls,
        "yes_votes": 0,
        "no_votes":  0,
        "voters":    [],
        "created":   datetime.datetime.utcnow()
    }
    polls_col.insert_one(doc)

    lines = ["✅ *Poll भेज दिया!*\n", f"📋 *Question:* {question}\n",
             f"📢 Channel: {'✅' if 'Channel' in sent_polls else '❌'}",
             f"💬 Group: {'✅' if 'Group' in sent_polls else '❌'}"]
    if errors:
        lines += errors
    bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")
    user_data.pop(uid, None)

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    poll_id   = poll_answer.poll_id
    user_id   = poll_answer.user.id
    username  = poll_answer.user.first_name
    option_id = poll_answer.option_ids[0] if poll_answer.option_ids else None

    poll_doc = None
    for doc in polls_col.find():
        for chat_name, info in doc.get("polls", {}).items():
            if info.get("poll_id") == poll_id:
                poll_doc = doc
                break
        if poll_doc:
            break

    if not poll_doc:
        return

    if user_id in poll_doc.get("voters", []):
        return

    if option_id == 0:
        polls_col.update_one({"_id": poll_doc["_id"]},
            {"$inc": {"yes_votes": 1}, "$push": {"voters": user_id}})
        vote_text = "✅ हाँ"
    else:
        polls_col.update_one({"_id": poll_doc["_id"]},
            {"$inc": {"no_votes": 1}, "$push": {"voters": user_id}})
        vote_text = "❌ नहीं"

    try:
        bot.send_message(ADMIN_ID,
            f"🗳️ *New Vote!*\n\n"
            f"👤 *User:* {username} (`{user_id}`)\n"
            f"📋 *Poll:* {poll_doc['question']}\n"
            f"✏️ *Vote:* {vote_text}",
            parse_mode="Markdown")
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data == "poll_results")
def poll_results(call):
    if not is_admin(call.from_user.id): return
    all_polls = list(polls_col.find().sort("_id", -1).limit(10))
    if not all_polls:
        bot.answer_callback_query(call.id, "😕 कोई poll नहीं।", show_alert=True)
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in all_polls:
        q = p['question'][:35] + "..." if len(p['question']) > 35 else p['question']
        total = p.get('yes_votes', 0) + p.get('no_votes', 0)
        markup.add(types.InlineKeyboardButton(
            f"📊 {q} ({total} votes)", callback_data=f"presult_{p['_id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))
    bot.edit_message_text("📈 *Poll Results:*", call.message.chat.id, call.message.message_id,
                          reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("presult_"))
def show_poll_result(call):
    if not is_admin(call.from_user.id): return
    p = polls_col.find_one({"_id": ObjectId(call.data.split("_", 1)[1])})
    if not p:
        bot.answer_callback_query(call.id, "Poll नहीं मिला।", show_alert=True)
        return
    yes = p.get('yes_votes', 0)
    no  = p.get('no_votes', 0)
    total = yes + no
    yes_pct = round(yes / total * 100, 1) if total else 0
    no_pct  = round(no  / total * 100, 1) if total else 0

    def bar(pct):
        f = int(pct / 10)
        return "🟩" * f + "⬜" * (10 - f)

    text = (
        f"📊 *Poll Result*\n\n"
        f"❓ *Q:* {p['question']}\n\n"
        f"✅ *हाँ:* {yes} ({yes_pct}%)\n{bar(yes_pct)}\n\n"
        f"❌ *नहीं:* {no} ({no_pct}%)\n{bar(no_pct)}\n\n"
        f"👥 *Total:* {total}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="poll_results"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                          reply_markup=markup, parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN ADD PLATFORM
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "admin_add")
def start_add(call):
    if not is_admin(call.from_user.id): return
    uid = call.from_user.id
    user_data[uid] = {'action': 'add'}
    msg = bot.send_message(uid,
        "➕ *नया Platform Add करें*\n\n"
        "1️⃣ Platform का *नाम* भेजें:\n_(e.g. TaskBucks, RozDhan)_",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_name)

def _step_name(message):
    uid = message.from_user.id
    if user_data.get(uid, {}).get('action') != 'add': return
    user_data[uid]['name'] = message.text.strip()
    msg = bot.send_message(uid, "2️⃣ *Referral / Earning Link* भेजें:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_link)

def _step_link(message):
    uid = message.from_user.id
    user_data[uid]['link'] = message.text.strip()
    msg = bot.send_message(uid, "3️⃣ *YouTube Tutorial Link* भेजें:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_tutorial)

def _step_tutorial(message):
    uid = message.from_user.id
    user_data[uid]['tutorial'] = message.text.strip()
    msg = bot.send_message(uid,
        "4️⃣ *1 घंटे में कितना?* (₹ में, e.g. 50)",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_per_hour)

def _step_per_hour(message):
    uid = message.from_user.id
    try:
        user_data[uid]['per_hour'] = float(message.text.strip().replace('₹','').replace(',',''))
    except ValueError:
        msg = bot.send_message(uid, "❌ सिर्फ नंबर भेजें (e.g. 50):")
        bot.register_next_step_handler(msg, _step_per_hour)
        return
    msg = bot.send_message(uid,
        "5️⃣ *Total कितना कमाया जा सकता है?* (Unlimited = 0)",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_max_total)

def _step_max_total(message):
    uid = message.from_user.id
    try:
        user_data[uid]['max_total'] = float(message.text.strip().replace('₹','').replace(',',''))
    except ValueError:
        msg = bot.send_message(uid, "❌ सिर्फ नंबर भेजें:")
        bot.register_next_step_handler(msg, _step_max_total)
        return
    msg = bot.send_message(uid, "6️⃣ *Withdrawal Time?* (e.g. 24 घंटे)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_withdraw_time)

def _step_withdraw_time(message):
    uid = message.from_user.id
    user_data[uid]['withdraw_time'] = message.text.strip()
    msg = bot.send_message(uid, "7️⃣ *Proof Photo* अपलोड करें 📸:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_proof_photo)

def _step_proof_photo(message):
    uid = message.from_user.id
    if message.content_type != 'photo':
        msg = bot.send_message(uid, "❌ सिर्फ Photo भेजें:")
        bot.register_next_step_handler(msg, _step_proof_photo)
        return

    file_id = message.photo[-1].file_id
    d = user_data[uid]
    d['photo'] = file_id

    doc = {
        "name": d['name'], "link": d['link'], "tutorial": d['tutorial'],
        "per_hour": d['per_hour'], "max_total": d['max_total'],
        "withdraw_time": d['withdraw_time'], "photo": file_id,
        "added": datetime.datetime.utcnow()
    }
    col.insert_one(doc)

    total_str = f"₹{d['max_total']:,.0f}" if d['max_total'] > 0 else "Unlimited 🚀"
    caption = (
        f"🔥 *NEW EARNING APP ALERT* 🔥\n\n"
        f"📌 *Name:* {d['name']}\n"
        f"⏱ *Per Hour:* ₹{d['per_hour']:,.0f}\n"
        f"💰 *Total:* {total_str}\n"
        f"🏦 *Withdrawal:* {d['withdraw_time']}\n"
        f"✅ *Status:* Verified & Working\n\n"
        f"👇 *Register करें:*\n{d['link']}"
    )
    post_markup = types.InlineKeyboardMarkup()
    post_markup.add(
        types.InlineKeyboardButton("🔗 Register Now",   url=d['link']),
        types.InlineKeyboardButton("📺 Watch Tutorial", url=d['tutorial'])
    )

    for chat in (CHANNEL_ID, GROUP_ID):
        try:
            bot.send_photo(chat, file_id, caption=caption,
                           reply_markup=post_markup, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(uid, f"⚠️ `{chat}` mein post fail: {e}", parse_mode="Markdown")

    bot.send_message(uid, "✅ *Save & Post हो गया दोनों जगह!*", parse_mode="Markdown")
    user_data.pop(uid, None)

# ═══════════════════════════════════════════════════════════════════════════════
#  VIEW PLATFORMS
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "view_links")
def view_links(call):
    uid = call.from_user.id
    track_user(call.from_user)

    if not check_membership(uid) and not is_admin(uid):
        bot.answer_callback_query(call.id, "❌ Channel & Group join करें!", show_alert=True)
        return

    apps = list(col.find())
    if not apps:
        bot.answer_callback_query(call.id, "😕 अभी कोई platform नहीं है।", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for app in apps:
        total_str = f"₹{app.get('max_total',0):,.0f}" if app.get('max_total', 0) > 0 else "∞"
        label = f"⭐ {app['name']}  |  ⏱₹{app.get('per_hour',0):,.0f}/hr  |  💰{total_str}"
        markup.add(types.InlineKeyboardButton(label, callback_data=f"show_{app['_id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))

    bot.edit_message_text(
        f"📋 *सभी Earning Platforms ({len(apps)}):*\n_Click करें details देखें 👇_",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("show_"))
def show_single(call):
    track_user(call.from_user)
    try:
        app = col.find_one({"_id": ObjectId(call.data.split("_", 1)[1])})
    except Exception:
        bot.answer_callback_query(call.id, "❌ Error।", show_alert=True)
        return
    if not app:
        bot.answer_callback_query(call.id, "❌ Platform delete हो चुका।", show_alert=True)
        return

    total_str = f"₹{app.get('max_total',0):,.0f}" if app.get('max_total', 0) > 0 else "Unlimited 🚀"
    caption = (
        f"⭐ *{app['name']}*\n\n"
        f"⏱ *Per Hour:* ₹{app.get('per_hour',0):,.0f}\n"
        f"💰 *Total Potential:* {total_str}\n"
        f"🏦 *Withdrawal:* {app.get('withdraw_time','N/A')}\n\n"
        f"🔗 *Link:* {app['link']}\n"
        f"📺 *Tutorial:* {app['tutorial']}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🔗 Register Now",   url=app['link']),
        types.InlineKeyboardButton("📺 Watch Tutorial", url=app['tutorial'])
    )
    markup.add(types.InlineKeyboardButton("🔙 Back to List", callback_data="view_links"))
    bot.send_photo(call.message.chat.id, app['photo'], caption=caption,
                   reply_markup=markup, parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN DELETE
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "admin_delete")
def admin_delete_list(call):
    if not is_admin(call.from_user.id): return
    apps = list(col.find())
    if not apps:
        bot.answer_callback_query(call.id, "😕 कोई platform नहीं।", show_alert=True)
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for app in apps:
        markup.add(types.InlineKeyboardButton(f"🗑️ {app['name']}", callback_data=f"del_{app['_id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))
    bot.edit_message_text("🗑️ *Delete करने के लिए चुनें:*",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def confirm_delete(call):
    if not is_admin(call.from_user.id): return
    oid = call.data.split("_", 1)[1]
    app = col.find_one({"_id": ObjectId(oid)})
    if not app:
        bot.answer_callback_query(call.id, "Already deleted.", show_alert=True)
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ हाँ Delete करो", callback_data=f"confirmed_{oid}"),
        types.InlineKeyboardButton("❌ Cancel",          callback_data="admin_delete")
    )
    bot.edit_message_text(f"⚠️ *{app['name']}* को delete करें?",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirmed_"))
def do_delete(call):
    if not is_admin(call.from_user.id): return
    result = col.delete_one({"_id": ObjectId(call.data.split("_", 1)[1])})
    msg = "✅ Delete हो गया!" if result.deleted_count else "❌ Already deleted."
    bot.answer_callback_query(call.id, msg, show_alert=True)
    admin_delete_list(call)

# ─── Back ─────────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_main(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    _show_main_menu(call.from_user.id, call.from_user.first_name)

# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("✅ Bot start ho raha hai...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
