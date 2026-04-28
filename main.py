import telebot
from telebot import types
from pymongo import MongoClient
from bson.objectid import ObjectId
import os

# ─── Configuration ────────────────────────────────────────────────────────────
API_TOKEN  = os.getenv('BOT_TOKEN')
MONGO_URI  = os.getenv('MONGO_URI')
ADMIN_ID   = int(os.getenv('ADMIN_ID'))
CHANNEL_ID = os.getenv('CHANNEL_ID')
GROUP_ID   = os.getenv('GROUP_ID')

bot    = telebot.TeleBot(API_TOKEN, parse_mode=None)
client = MongoClient(MONGO_URI)
db     = client['earning_db']
col    = db['platforms']
polls_col = db['polls']   # polls store होंगे यहाँ

user_data: dict = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def check_membership(user_id: int) -> bool:
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
    markup.add(
        types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"),
        types.InlineKeyboardButton("💬 Join Group",   url=f"https://t.me/{GROUP_ID.lstrip('@')}")
    )
    markup.add(types.InlineKeyboardButton("✅ Join कर लिया – Continue", callback_data="check_join"))
    return markup

# ─── /start ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
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
    markup.add(types.InlineKeyboardButton("🚀 सभी Earning Platforms देखें", callback_data="view_links"))

    if chat_id == ADMIN_ID:
        markup.add(
            types.InlineKeyboardButton("➕ नया Platform Add करें",  callback_data="admin_add"),
            types.InlineKeyboardButton("🗑️ Platform Delete करें",   callback_data="admin_delete"),
            types.InlineKeyboardButton("📊 Total Platforms Count",  callback_data="admin_count"),
            types.InlineKeyboardButton("📣 Poll भेजें",             callback_data="admin_poll"),
            types.InlineKeyboardButton("📈 Poll Results देखें",     callback_data="poll_results"),
        )

    bot.send_message(
        chat_id,
        f"👋 नमस्ते *{first_name}*!\n\n"
        f"💸 *Earning Bot* में आपका स्वागत है।\n"
        f"नीचे से काम चुनें 👇",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ─── Force Join Check ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "check_join")
def recheck_join(call):
    uid = call.from_user.id
    if check_membership(uid):
        bot.answer_callback_query(call.id, "✅ Verified! Welcome!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        _show_main_menu(uid, call.from_user.first_name)
    else:
        bot.answer_callback_query(call.id, "❌ अभी join नहीं किया।", show_alert=True)

# ─── Admin Count ──────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_count")
def admin_count(call):
    if not is_admin(call.from_user.id): return
    n = col.count_documents({})
    bot.answer_callback_query(call.id, f"📊 Total Platforms: {n}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN: POLL SEND
#  Admin poll question type करेगा → Channel + Group दोनों में भेजेगा
#  Poll votes MongoDB में save होंगे
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "admin_poll")
def start_poll(call):
    if not is_admin(call.from_user.id): return
    uid = call.from_user.id
    user_data[uid] = {'action': 'poll'}
    msg = bot.send_message(
        uid,
        "📣 *नया Poll बनाएं*\n\n"
        "Poll का *Question* भेजें:\n"
        "_(e.g. क्या यह नया Earning Platform लाना चाहिए?)_",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, _poll_question)

def _poll_question(message):
    uid = message.from_user.id
    user_data[uid]['question'] = message.text.strip()

    # Options fixed: Yes/No
    question = user_data[uid]['question']

    sent_polls = {}
    errors = []

    for chat_id, chat_name in [(CHANNEL_ID, "Channel"), (GROUP_ID, "Group")]:
        try:
            sent = bot.send_poll(
                chat_id,
                question=question,
                options=["✅ हाँ, लाओ!", "❌ नहीं चाहिए"],
                is_anonymous=False,   # votes track करने के लिए
                allows_multiple_answers=False,
                open_period=86400     # 24 घंटे open रहेगा
            )
            sent_polls[chat_name] = {
                "chat_id": chat_id,
                "message_id": sent.message_id,
                "poll_id": sent.poll.id
            }
        except Exception as e:
            errors.append(f"⚠️ {chat_name}: {e}")

    # MongoDB में save करो
    doc = {
        "question": question,
        "polls": sent_polls,
        "yes_votes": 0,
        "no_votes": 0,
        "voters": []   # duplicate vote रोकने के लिए
    }
    polls_col.insert_one(doc)

    feedback = "✅ *Poll भेज दिया गया!*\n\n"
    feedback += f"📋 *Question:* {question}\n"
    feedback += f"📍 Channel: {'✅' if 'Channel' in sent_polls else '❌'}\n"
    feedback += f"📍 Group: {'✅' if 'Group' in sent_polls else '❌'}\n"
    if errors:
        feedback += "\n" + "\n".join(errors)

    bot.send_message(uid, feedback, parse_mode="Markdown")
    user_data.pop(uid, None)

# ─── Poll Answer Handler (जब कोई poll में vote करे) ──────────────────────────
@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    """
    यह handler तब चलता है जब कोई user poll में vote करता है।
    poll_answer.poll_id  → कौन सा poll
    poll_answer.user     → किसने vote किया
    poll_answer.option_ids → [0] = Yes, [1] = No
    """
    poll_id   = poll_answer.poll_id
    user_id   = poll_answer.user.id
    username  = poll_answer.user.first_name
    option_id = poll_answer.option_ids[0] if poll_answer.option_ids else None

    # MongoDB में poll ढूंढो
    poll_doc = polls_col.find_one({"polls": {"$elemMatch": {"poll_id": poll_id}}})

    # Alternate search method
    if not poll_doc:
        for doc in polls_col.find():
            for chat_name, info in doc.get("polls", {}).items():
                if info.get("poll_id") == poll_id:
                    poll_doc = doc
                    break

    if not poll_doc:
        return  # Poll नहीं मिला

    doc_id = poll_doc["_id"]

    # Duplicate vote check
    if user_id in poll_doc.get("voters", []):
        return  # पहले से vote किया है

    # Vote count update
    if option_id == 0:
        polls_col.update_one(
            {"_id": doc_id},
            {"$inc": {"yes_votes": 1}, "$push": {"voters": user_id}}
        )
        vote_text = "✅ हाँ"
    else:
        polls_col.update_one(
            {"_id": doc_id},
            {"$inc": {"no_votes": 1}, "$push": {"voters": user_id}}
        )
        vote_text = "❌ नहीं"

    # Admin को notify करो
    try:
        bot.send_message(
            ADMIN_ID,
            f"🗳️ *New Vote आया!*\n\n"
            f"👤 *User:* {username} (`{user_id}`)\n"
            f"📋 *Poll:* {poll_doc['question']}\n"
            f"✏️ *Vote:* {vote_text}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

# ─── Poll Results देखें ───────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "poll_results")
def poll_results(call):
    if not is_admin(call.from_user.id): return

    all_polls = list(polls_col.find().sort("_id", -1).limit(10))

    if not all_polls:
        bot.answer_callback_query(call.id, "😕 अभी कोई poll नहीं है।", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in all_polls:
        q = p['question'][:35] + "..." if len(p['question']) > 35 else p['question']
        total = p.get('yes_votes', 0) + p.get('no_votes', 0)
        markup.add(types.InlineKeyboardButton(
            f"📊 {q} ({total} votes)",
            callback_data=f"presult_{p['_id']}"
        ))

    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))
    bot.edit_message_text(
        "📈 *Poll Results – Select करें:*",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("presult_"))
def show_poll_result(call):
    if not is_admin(call.from_user.id): return
    oid = call.data.split("_", 1)[1]
    p   = polls_col.find_one({"_id": ObjectId(oid)})
    if not p:
        bot.answer_callback_query(call.id, "Poll नहीं मिला।", show_alert=True)
        return

    yes   = p.get('yes_votes', 0)
    no    = p.get('no_votes', 0)
    total = yes + no

    yes_pct = round((yes / total * 100), 1) if total > 0 else 0
    no_pct  = round((no  / total * 100), 1) if total > 0 else 0

    # Progress bar बनाओ
    def bar(pct):
        filled = int(pct / 10)
        return "🟩" * filled + "⬜" * (10 - filled)

    text = (
        f"📊 *Poll Result*\n\n"
        f"❓ *Question:* {p['question']}\n\n"
        f"✅ *हाँ:* {yes} votes ({yes_pct}%)\n"
        f"{bar(yes_pct)}\n\n"
        f"❌ *नहीं:* {no} votes ({no_pct}%)\n"
        f"{bar(no_pct)}\n\n"
        f"👥 *Total Votes:* {total}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="poll_results"))
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown"
    )

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
    msg = bot.send_message(uid, "2️⃣ *Referral / Earning Link* (URL) भेजें:", parse_mode="Markdown")
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
        "4️⃣ *1 घंटे में कितना कमाया जा सकता है?* (₹)\n_(e.g. 50)_",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_per_hour)

def _step_per_hour(message):
    uid = message.from_user.id
    try:
        user_data[uid]['per_hour'] = float(message.text.strip().replace('₹','').replace(',',''))
    except ValueError:
        msg = bot.send_message(uid, "❌ सिर्फ नंबर भेजें (e.g. 50). फिर से:")
        bot.register_next_step_handler(msg, _step_per_hour)
        return
    msg = bot.send_message(uid,
        "5️⃣ *Total कितना कमाया जा सकता है?* (₹)\n_(Unlimited = 0 लिखें)_",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_max_total)

def _step_max_total(message):
    uid = message.from_user.id
    try:
        user_data[uid]['max_total'] = float(message.text.strip().replace('₹','').replace(',',''))
    except ValueError:
        msg = bot.send_message(uid, "❌ सिर्फ नंबर भेजें. फिर से:")
        bot.register_next_step_handler(msg, _step_max_total)
        return
    msg = bot.send_message(uid,
        "6️⃣ *Withdrawal कितने घंटे/दिन में होता है?*\n_(e.g. 24 घंटे)_",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_withdraw_time)

def _step_withdraw_time(message):
    uid = message.from_user.id
    user_data[uid]['withdraw_time'] = message.text.strip()
    msg = bot.send_message(uid, "7️⃣ *Withdrawal Proof Photo* अपलोड करें 📸:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, _step_proof_photo)

def _step_proof_photo(message):
    uid = message.from_user.id
    if message.content_type != 'photo':
        msg = bot.send_message(uid, "❌ सिर्फ *Photo* भेजें। फिर से:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, _step_proof_photo)
        return

    file_id = message.photo[-1].file_id
    d = user_data[uid]
    d['photo'] = file_id

    doc = {
        "name": d['name'], "link": d['link'], "tutorial": d['tutorial'],
        "per_hour": d['per_hour'], "max_total": d['max_total'],
        "withdraw_time": d['withdraw_time'], "photo": file_id,
    }
    col.insert_one(doc)

    total_str = f"₹{d['max_total']:,.0f}" if d['max_total'] > 0 else "Unlimited 🚀"
    caption = (
        f"🔥 *NEW EARNING APP ALERT* 🔥\n\n"
        f"📌 *Name:* {d['name']}\n"
        f"⏱ *Per Hour:* ₹{d['per_hour']:,.0f}\n"
        f"💰 *Total Potential:* {total_str}\n"
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
            bot.send_message(uid, f"⚠️ Post failed `{chat}`: {e}", parse_mode="Markdown")

    bot.send_message(uid, "✅ *Save हो गया और दोनों जगह post हो गया!*", parse_mode="Markdown")
    user_data.pop(uid, None)

# ═══════════════════════════════════════════════════════════════════════════════
#  VIEW PLATFORMS
# ═══════════════════════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "view_links")
def view_links(call):
    uid = call.from_user.id
    if not check_membership(uid) and not is_admin(uid):
        bot.answer_callback_query(call.id, "❌ Channel & Group join करें!", show_alert=True)
        return

    apps = list(col.find())
    if not apps:
        bot.answer_callback_query(call.id, "😕 अभी कोई platform नहीं है।", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for app in apps:
        total_str = f"₹{app['max_total']:,.0f}" if app.get('max_total', 0) > 0 else "Unlimited"
        label = f"⭐ {app['name']}  |  ⏱₹{app.get('per_hour',0):,.0f}/hr  |  💰{total_str}"
        markup.add(types.InlineKeyboardButton(label, callback_data=f"show_{app['_id']}"))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_main"))

    bot.edit_message_text(
        "📋 *सभी Earning Platforms:*\n_Click करें details देखें 👇_",
        call.message.chat.id, call.message.message_id,
        reply_markup=markup, parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("show_"))
def show_single(call):
    try:
        app = col.find_one({"_id": ObjectId(call.data.split("_", 1)[1])})
    except Exception:
        bot.answer_callback_query(call.id, "❌ Error।", show_alert=True)
        return
    if not app:
        bot.answer_callback_query(call.id, "❌ Platform delete हो चुका।", show_alert=True)
        return

    total_str = f"₹{app['max_total']:,.0f}" if app.get('max_total', 0) > 0 else "Unlimited 🚀"
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
        types.InlineKeyboardButton("🔗 Register Now",    url=app['link']),
        types.InlineKeyboardButton("📺 Watch Tutorial",  url=app['tutorial'])
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
    print("✅ Bot चालू है...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
