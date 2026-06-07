import telebot
import logging
import os
import time
import secrets
from flask import Flask, request, redirect
from werkzeug.security import generate_password_hash
from config.settings import BOT_TOKEN, ADMIN_ID, MESSAGES, WEB_APP_URL
from database.mongodb import init_db, get_db
from keyboards.telebot_keyboards import (
    admin_main_menu,
    warehouse_list_menu,
    warehouse_actions_menu,
    branches_menu,
    back_button,
    product_types_menu,
    products_by_type_menu,
    product_type_actions_menu,
    branches_selection_menu,
    user_main_menu,
    user_request_menu,
    user_warehouse_menu,
    product_types_menu_user,
    products_by_type_menu_user,
    branches_menu_user,
    remove_description_menu,
    remove_target_branch_menu,
    remove_quantity_back_menu,
    input_quantity_back_menu,
    list_branches_menu,
    admin_settings_menu,
    units_menu,
    units_choose_menu,
)
# Line 30 dan keyin qo'shish:
from groups.handlers import register_group_handlers
from admin_users.handlers import register_admin_users_handlers
from web.routes import register_web_routes
from web.app_links import get_app_button_kwargs, make_login_message
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Database initialization with retry logic
logger.info("🔌 MongoDB baza Ishga Tushirilmoqda...")
db_initialized = False
for attempt in range(3):
    try:
        init_db()
        logger.info("✅ MongoDB baza tayyor")
        db_initialized = True
        break
    except Exception as e:
        logger.error(f"❌ MongoDB ulanish xatosi (Urinish {attempt + 1}/3): {e}")
        if attempt < 2:
            time.sleep(2)  # Wait 2 seconds before retrying

if not db_initialized:
    logger.warning("⚠️ MongoDB baza ulanmadi. App blokirovkasiz ishga tushirildi (faqat xavfsizlik uchun)")

# ==================== USER STATE STORAGE ====================
user_states = {}


def _app_only_menu(role="customer"):
    """Faqat web/mini ilova tugmasini ko'rsatadigan menyu."""
    markup = telebot.types.InlineKeyboardMarkup()
    button_kwargs = get_app_button_kwargs(role)
    if button_kwargs:
        markup.add(telebot.types.InlineKeyboardButton("📱 Ilova", **button_kwargs))
    return markup


def _request_role_menu(user_id):
    """Admin tasdiqdan keyin foydalanuvchi toifasini tanlash menyusi."""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("👷 Xodim", callback_data=f"approve_user_role:{user_id}:employee"),
        telebot.types.InlineKeyboardButton("🧑‍💼 Mijoz", callback_data=f"approve_user_role:{user_id}:customer"),
    )
    markup.add(telebot.types.InlineKeyboardButton("❌ Rad Qilish", callback_data=f"reject_user:{user_id}"))
    return markup

def _safe_delete_message(chat_id, message_id):
    """Xabarni imkon qadar o'chiradi (xatolarni yutadi)."""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _get_product_display_image(product=None, product_type=None):
    """Mahsulot rasmi bo'lsa o'shani, bo'lmasa tur rasmini qaytaradi."""
    if product and product.get("image_id"):
        return product["image_id"]
    if product_type and product_type.get("image_id"):
        return product_type["image_id"]
    return None


def _show_product_types_message(chat_id, message_id, warehouse, branch):
    """Mahsulot turlari oynasini rasm bo'lsa caption orqali, bo'lmasa text orqali yangilash"""
    branch_display = branch if branch != "common" else "🌍 Umumiy Bo'lim"
    text = f"📦 {branch_display}\n\nMahsulot turini tanlang yoki yangi qo'shish:"
    markup = product_types_menu(warehouse, branch)

    db = get_db()
    types = db.get_all_product_types(warehouse, branch)
    image_id = next((ptype.get("image_id") for ptype in types if ptype.get("image_id")), None)

    if image_id:
        try:
            bot.edit_message_caption(
                caption=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

        bot.send_photo(chat_id, image_id, caption=text, reply_markup=markup, parse_mode="HTML")
        return

    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        try:
            bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


def _show_products_by_type_message(chat_id, message_id, warehouse, branch, product_type):
    """Mahsulot ro'yxatini tur rasmi bilan doim qayta ko'rsatish"""
    db = get_db()
    ptype = db.get_product_type_by_name(product_type, warehouse, branch)
    text = f"📦 {product_type}\n\nMahsulot tanlang yoki yangi qo'shish:"
    markup = products_by_type_menu(warehouse, branch, product_type)

    if ptype and ptype.get("image_id"):
        try:
            bot.edit_message_media(
                media=telebot.types.InputMediaPhoto(ptype["image_id"], caption=text, parse_mode="HTML"),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

        bot.send_photo(chat_id, ptype["image_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        return

    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        try:
            bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


def _show_product_details_message(chat_id, message_id, warehouse, branch, product_type, product_name):
    """Mahsulot detali: yuqorida tur rasmi, pastda nom va amallar"""
    db = get_db()
    ptype = db.get_product_type_by_name(product_type, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type)
    product_code = product.get("code") if product else "-"
    product_unit = product.get("unit", "dona") if product else "dona"
    text = (
        f"📦 <b>{product_name}</b>\n"
        f"🔢 Kod: <b>{product_code}</b>\n\n"
        f"📏 Birlik: <b>{product_unit}</b>\n\n"
        "Amalni tanlang:"
    )

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(
            "✏️ Tahrirlash",
            callback_data=f"product_edit:{warehouse}:{branch}:{product_type}:{product_name}",
        ),
        telebot.types.InlineKeyboardButton(
            "🗑️ O'chirish",
            callback_data=f"product_delete:{warehouse}:{branch}:{product_type}:{product_name}",
        ),
    )
    markup.add(
        telebot.types.InlineKeyboardButton(
            MESSAGES["button_back"], callback_data=f"product_list_back:{warehouse}:{branch}:{product_type}"
        )
    )

    image_id = _get_product_display_image(product, ptype)

    if image_id and message_id:
        try:
            bot.edit_message_media(
                media=telebot.types.InputMediaPhoto(image_id, caption=text, parse_mode="HTML"),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        bot.send_photo(chat_id, image_id, caption=text, reply_markup=markup, parse_mode="HTML")
        return

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        
        
# ==================== /START ====================

@bot.message_handler(commands=['start'])
def handle_start(message):
    """Bot /start qilish"""
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name or "Foydalanuvchi"
    
    # ✅ STATE O'CHIRISH
    if user_id in user_states:
        old_state = user_states.pop(user_id)
        logger.info(f"🗑️ /start: {user_id} ning state o'chirildi")
    
    db = get_db()
    user = db.get_user(user_id)
    
    if user_id == ADMIN_ID:
        # ✅ ADMIN: SKLAD RO'YXATI BIRINCHI!
        bot.send_message(
            user_id,
            "👤 Salom, Administrator!\n\nIshlash uchun skladni tanlang:",
            reply_markup=warehouse_list_menu()
        )
    elif user and user.get("approved"):
        role = user.get("role") or "employee"
        if role == "customer":
            bot.send_message(
                user_id,
                f"👋 Salom, {first_name}!\n\nIlovaga kirish uchun tugmani bosing:",
                reply_markup=_app_only_menu("customer"),
            )
        else:
            bot.send_message(
                user_id,
                f"👋 Salom, {first_name}!\n\nAvval skladni tanlang:",
                reply_markup=user_warehouse_menu(),
            )
    else:
        if not user:
            db.add_user(user_id, username, first_name, approved=False)
        bot.send_message(
            user_id,
            "Tizimdan foydalanish uchun admin tasdiqlashi kerak.\n\nIltimos, telefon raqamingizni kontakt sifatida yuboring.",
            reply_markup=user_request_menu(),
        )

# ==================== WAREHOUSE HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data == "warehouse_list")
def handle_warehouse_list(call):
    """Sklad ro'yxati"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    bot.edit_message_text(
        "🏭 Skladlar ro'yxati:\n\nSklad tanlang yoki yangi qo'shish:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=warehouse_list_menu()
    )

# YANGI (Line 273):
@bot.callback_query_handler(func=lambda call: call.data == "admin_settings")
def handle_admin_settings(call):
    """Admin sozlamalari"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    user_states.pop(call.from_user.id, None)
    bot.edit_message_text(
        "⚙️ Boshqarish bo'limi:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_settings_menu(),
    )

@bot.callback_query_handler(func=lambda call: call.data == "units_menu")
def handle_units_menu(call):
    """Birliklar oynasi"""
    user_states.pop(call.from_user.id, None)
    bot.edit_message_text(
        "📏 Birliklar ro'yxati:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=units_menu(),
    )

@bot.callback_query_handler(func=lambda call: call.data == "unit_add")
def handle_unit_add(call):
    user_states[call.from_user.id] = {"action": "waiting_unit_name"}
    bot.send_message(
        call.message.chat.id,
        "✍️ Yangi birlik nomini kiriting:",
        reply_markup=back_button("units_menu"),
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "waiting_unit_name")
def process_unit_add(message):
    """Birlik qo'shish"""
    name = message.text.strip()
    if not name:
        bot.send_message(message.chat.id, "❌ Birlik nomi bo'sh bo'lishi mumkin emas")
        return
    db = get_db()
    if db.add_unit(name):
        bot.send_message(message.chat.id, f"✅ '{name}' birligi qo'shildi", reply_markup=units_menu())
    else:
        bot.send_message(message.chat.id, "❌ Bu birlik allaqachon mavjud", reply_markup=units_menu())
    user_states.pop(message.from_user.id, None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unit_select:"))
def handle_unit_select(call):
    unit_name = call.data.split(":", 1)[1]
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"unit_delete_yes:{unit_name}"),
        telebot.types.InlineKeyboardButton(MESSAGES["button_back"], callback_data="units_menu"),
    )
    bot.edit_message_text(
        f"⚠️ <b>{unit_name}</b> birligini o'chirasizmi?",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML",
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("unit_delete_yes:"))
def handle_unit_delete_yes(call):
    unit_name = call.data.split(":", 1)[1]
    db = get_db()
    db.delete_unit(unit_name)
    bot.edit_message_text(
        f"🗑️ '{unit_name}' o'chirildi.\n\n📏 Birliklar ro'yxati:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=units_menu(),
    )

# ✅ WAREHOUSE ADD
@bot.callback_query_handler(func=lambda call: call.data == "warehouse_add")
def handle_warehouse_add(call):
    """Yangi sklad qo'shish"""
    user_id = call.from_user.id
    
    logger.info(f"🟡 CALLBACK: warehouse_add for user {user_id}")
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    
    user_states[user_id] = {"action": "waiting_warehouse_name"}
    logger.info(f"✅ State set: waiting_warehouse_name")
    
    bot.send_message(
        call.message.chat.id,
        "✍️ Sklad nomini kiriting:",
        reply_markup=back_button("warehouse_list")
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "waiting_warehouse_name")
def process_warehouse_add(message):
    """Sklad nomini saqlash"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    logger.info(f"🔴 WAREHOUSE MESSAGE: user_id={user_id}, text='{name}', state={user_states.get(user_id)}")
    
    if user_states.get(user_id, {}).get("action") != "waiting_warehouse_name":
        logger.warning(f"❌ State mismatch")
        bot.send_message(message.chat.id, "❌ Avval /start bosing")
        return
    
    if not name:
        bot.send_message(message.chat.id, "❌ Sklad nomi bo'sh bo'lishi mumkin emas")
        return
    
    db = get_db()
    
    if db.add_warehouse(name):
        user_states.pop(user_id, None)
        logger.info(f"✅ Warehouse added: '{name}'")
        
        bot.send_message(
            message.chat.id,
            f"✅ '{name}' skladi qo'shildi!",
            reply_markup=warehouse_list_menu()
        )
    else:
        user_states.pop(user_id, None)
        logger.warning(f"❌ Warehouse already exists: '{name}'")
        
        bot.send_message(
            message.chat.id,
            f"❌ '{name}' skladi allaqachon mavjud!",
            reply_markup=back_button("warehouse_list")
        )

# ✅ WAREHOUSE SELECT
@bot.callback_query_handler(func=lambda call: call.data.startswith("warehouse_select:"))
def handle_warehouse_select(call):
    """Skladni tanlash"""
    warehouse_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    user_states[user_id] = {"action": "viewing_warehouse", "warehouse": warehouse_name}
    
    bot.edit_message_text(
        f"👤 Salom, Administrator!\n\n🏭 Sklad: <b>{warehouse_name}</b>\n\nIshlash uchun tugmani tanlang:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_main_menu(warehouse_name),
        parse_mode="HTML"
    )

# ✅ WAREHOUSE ACTIONS
@bot.callback_query_handler(func=lambda call: call.data.startswith("warehouse_actions:"))
def handle_warehouse_actions(call):
    """Sklad faoliyatlari"""
    warehouse_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    user_states[user_id] = {"action": "viewing_warehouse", "warehouse": warehouse_name}
    
    bot.edit_message_text(
        f"🏭 <b>{warehouse_name}</b>\n\nFaoliyatni tanlang:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=warehouse_actions_menu(warehouse_name),
        parse_mode="HTML"
    )

# ✅ WAREHOUSE EDIT
@bot.callback_query_handler(func=lambda call: call.data.startswith("warehouse_edit:"))
def handle_warehouse_edit(call):
    """Sklad tahrirlash"""
    warehouse_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    user_states[user_id] = {"action": "editing_warehouse", "old_name": warehouse_name}
    
    bot.send_message(
        call.message.chat.id,
        "✍️ Yangi sklad nomini kiriting:",
        reply_markup=back_button("warehouse_list")
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "editing_warehouse")
def process_warehouse_edit(message):
    """Sklad nomini o'zgartirish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    old_name = data.get("old_name")
    new_name = message.text.strip()
    
    if not new_name:
        bot.send_message(message.chat.id, "❌ Sklad nomi bo'sh bo'lishi mumkin emas")
        return
    
    db = get_db()
    if db.update_warehouse(old_name, new_name):
        user_states.pop(user_id, None)
        logger.info(f"✅ Warehouse renamed: {old_name} -> {new_name}")
        bot.send_message(
            message.chat.id,
            f"✅ '{new_name}' nomiga o'zgartirildi!",
            reply_markup=warehouse_list_menu()
        )
    else:
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Xato yuz berdi", reply_markup=back_button("warehouse_list"))

# ✅ WAREHOUSE DELETE
@bot.callback_query_handler(func=lambda call: call.data.startswith("warehouse_delete:"))
def handle_warehouse_delete(call):
    """Sklad o'chirish"""
    warehouse_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    user_states[user_id] = {"action": "confirming_delete", "warehouse": warehouse_name}
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"warehouse_delete_confirm:{warehouse_name}"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="warehouse_list")
    )
    
    bot.send_message(
        call.message.chat.id,
        f"⚠️ '{warehouse_name}' skladini o'chirasizmi?\n\nBu amalni qaytarib bo'lmaydi!",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("warehouse_delete_confirm:"))
def handle_warehouse_delete_confirm(call):
    """Sklad o'chirishni tasdiqlash"""
    warehouse_name = call.data.split(":")[1]
    user_id = call.from_user.id
    
    db = get_db()
    db.delete_warehouse(warehouse_name)
    
    user_states.pop(user_id, None)
    
    bot.edit_message_text(
        f"🗑️ '{warehouse_name}' skladi o'chirildi",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=warehouse_list_menu()
    )

# ==================== BRANCH HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_branch:"))
def handle_admin_branch(call):
    """Admin filial boshqarish"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    
    warehouse = call.data.split(":")[1]
    user_id = call.from_user.id
    user_states[user_id] = {"warehouse": warehouse}
    
    bot.edit_message_text(
        MESSAGES["branch_management"],
        call.message.chat.id,
        call.message.message_id,
        reply_markup=branches_menu(warehouse)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_add:"))
def handle_branch_add(call):
    """Filial qo'shish"""
    warehouse = call.data.split(":")[1]
    user_id = call.from_user.id
    
    user_states[user_id] = {"warehouse": warehouse}
    
    bot.send_message(
        call.message.chat.id,
        MESSAGES["branch_add_prompt"],
        reply_markup=back_button(f"admin_branch:{warehouse}")
    )
    user_states[user_id] = {"warehouse": warehouse, "state": "waiting_branch_name"}

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("state") == "waiting_branch_name")
def process_branch_add(message):
    """Filial nomini saqlash"""
    db = get_db()
    name = message.text.strip()
    user_id = message.from_user.id
    
    warehouse = user_states.get(user_id, {}).get("warehouse")
    
    logger.info(f"📝 Branch handler: user_id={user_id}, text='{name}', warehouse='{warehouse}'")
    
    if not name:
        bot.send_message(message.chat.id, "❌ Filial nomi bo'sh bo'lishi mumkin emas")
        return
    
    if db.add_branch(name, warehouse):
        user_states.pop(user_id, None)
        logger.info(f"✅ Filial qo'shildi: {name}")
        bot.send_message(
            message.chat.id,
            MESSAGES["branch_added"].format(name),
            reply_markup=branches_menu(warehouse)
        )
    else:
        user_states.pop(user_id, None)
        bot.send_message(
            message.chat.id,
            MESSAGES["branch_exists"],
            reply_markup=back_button(f"admin_branch:{warehouse}")
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_select:"))
def handle_branch_select(call):
    """Filial tanlash"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch_name = parts[2]
    
    user_id = call.from_user.id
    user_states[user_id] = {"warehouse": warehouse, "branch": branch_name}
    
    _show_branch_actions(call.message.chat.id, call.message.message_id, warehouse, branch_name)


def _show_branch_actions(chat_id, message_id, warehouse, branch_name):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(MESSAGES["button_edit"], callback_data=f"branch_edit:{warehouse}:{branch_name}"),
        telebot.types.InlineKeyboardButton(MESSAGES["button_delete"], callback_data=f"branch_delete:{warehouse}:{branch_name}")
    )
    markup.add(telebot.types.InlineKeyboardButton(MESSAGES["button_back"], callback_data=f"admin_branch:{warehouse}"))
    
    bot.edit_message_text(
        f"🏢 Filial: <b>{branch_name}</b>\n\nFaoliyatni tanlang:",
        chat_id,
        message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_edit:"))
def handle_branch_edit(call):
    """Filial tahrirlash"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch_name = parts[2]
    
    user_id = call.from_user.id
    user_states[user_id] = {"action": "editing_branch", "warehouse": warehouse, "old_name": branch_name}
    
    bot.send_message(
        call.message.chat.id,
        "✍️ Yangi filial nomini kiriting:",
        reply_markup=back_button(f"admin_branch:{warehouse}")
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "editing_branch")
def process_branch_edit(message):
    """Filial nomini o'zgartirish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    warehouse = data.get("warehouse")
    old_name = data.get("old_name")
    new_name = message.text.strip()
    
    if not new_name:
        bot.send_message(message.chat.id, "❌ Filial nomi bo'sh bo'lishi mumkin emas")
        return
    
    db = get_db()
    if db.update_branch(old_name, new_name, warehouse):
        user_states.pop(user_id, None)
        logger.info(f"✅ Filial tahrirlandi: {old_name} -> {new_name}")
        bot.send_message(
            message.chat.id,
            MESSAGES["branch_renamed"].format(new_name),
            reply_markup=branches_menu(warehouse)
        )
    else:
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Xato yuz berdi", reply_markup=back_button(f"admin_branch:{warehouse}"))

@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_delete:"))
def handle_branch_delete(call):
    """Filial o'chirishni tasdiqlash oynasi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch_name = parts[2]

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"branch_delete_confirm:{warehouse}:{branch_name}"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data=f"branch_delete_cancel:{warehouse}:{branch_name}")
    )

    bot.edit_message_text(
        f"⚠️ <b>{branch_name}</b> bo'limini o'chirasizmi?",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML",
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_delete_confirm:"))
def handle_branch_delete_confirm(call):
    parts = call.data.split(":")
    warehouse = parts[1]
    branch_name = parts[2]
    
    db = get_db()
    db.delete_branch(branch_name, warehouse)
    
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    bot.edit_message_text(
        f"✅ <b>{branch_name}</b> bo'limi o'chirildi.\n\n{MESSAGES['branch_management']}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=branches_menu(warehouse),
        parse_mode="HTML"
    )
@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_delete_cancel:"))
def handle_branch_delete_cancel(call):
    parts = call.data.split(":")
    warehouse = parts[1]
    branch_name = parts[2]
    _show_branch_actions(call.message.chat.id, call.message.message_id, warehouse, branch_name)
    
# ==================== ADMIN PRODUCT HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_product:"))
def handle_admin_product(call):
    """Admin mahsulot tanlash - FILIALLAR RO'YXATI BIRINCHI"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    
    warehouse = call.data.split(":")[1]
    user_id = call.from_user.id
    user_states[user_id] = {"warehouse": warehouse}
    
    bot.edit_message_text(
        "🏢 Filial tanlang yoki Umumiy:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=branches_selection_menu(warehouse),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_branch_select:"))
def handle_product_branch_select(call):
    """Mahsulot turi tanlash uchun filial tanlandi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    
    user_id = call.from_user.id
    user_states[user_id] = {"warehouse": warehouse, "branch": branch}
    
    branch_display = branch if branch != "common" else "🌍 Umumiy Bo'lim"
    
    bot.edit_message_text(
        f"📦 {branch_display}\n\nMahsulot turini tanlang yoki yangi qo'shish:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=product_types_menu(warehouse, branch),
        parse_mode="HTML"
    )

# ✅ PRODUCT TYPE ADD - RASM BILAN!
@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_add:"))
def handle_product_type_add(call):
    """Yangi mahsulot turi qo'shish"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    
    user_id = call.from_user.id
    
    logger.info(f"🟡 CALLBACK: product_type_add for warehouse={warehouse}, branch={branch}")
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    
    user_states[user_id] = {
        "action": "waiting_product_type_name",
        "warehouse": warehouse,
        "branch": branch
    }
    
    bot.send_message(
        call.message.chat.id,
        "✍️ Mahsulot turi (brend) nomini kiriting:",
        reply_markup=back_button(f"product_branch_select:{warehouse}:{branch}")
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "waiting_product_type_name")
def process_product_type_add(message):
    """Mahsulot turi nomini saqlash"""
    user_id = message.from_user.id
    name = message.text.strip()
    
    current_state = user_states.get(user_id, {})
    logger.info(f"🔴 PRODUCT TYPE MESSAGE: user_id={user_id}, text='{name}', state={current_state}")
    
    if current_state.get("action") != "waiting_product_type_name":
        logger.warning(f"❌ State mismatch")
        bot.send_message(message.chat.id, "❌ Avval /start bosing")
        return
    
    if not name:
        bot.send_message(message.chat.id, "❌ Tur nomi bo'sh bo'lishi mumkin emas")
        return
    
    # ✅ RASM KERAK MI DEB SO'RASH!
    user_states[user_id] = {
        "action": "adding_product_type",
        "product_type_name": name,
        "warehouse": current_state.get("warehouse"),
        "branch": current_state.get("branch", "common"),
        "product_type_image_id": None,
    }
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_type_image_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_type_image_no")
    )
    
    bot.send_message(
        message.chat.id,
        f"Mahsulot turi: <b>{name}</b>\n\n🖼️ Rasm kerakmi?",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == "product_type_image_yes")
def handle_product_type_image_yes(call):
    """Rasm yuklash kerak"""
    user_id = call.from_user.id
    if user_id not in user_states or not isinstance(user_states[user_id], dict):
        bot.answer_callback_query(call.id, "Holat topilmadi, qayta urinib ko'ring", show_alert=True)
        return

    user_states[user_id]["action"] = "uploading_product_type_image"
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    
    bot.send_message(
        call.message.chat.id,
        "📷 Mahsulot turi uchun rasm yuboring:",
        reply_markup=back_button("product_type_image_cancel")
    )

def _ask_product_type_common_code(chat_id, user_id):
    data = user_states.get(user_id, {})
    data["action"] = "awaiting_product_type_common_code_decision"
    user_states[user_id] = data
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_type_common_code_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_type_common_code_no"),
    )
    bot.send_message(
        chat_id,
        "🔢 Bu tur uchun <b>umumiy kod</b> berasizmi?",
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.message_handler(content_types=['photo'], func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "uploading_product_type_image")
def process_product_type_image(message):
    """Mahsulot turi rasmi qabul qilish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    
    image_id = message.photo[-1].file_id
    data["product_type_image_id"] = image_id
    user_states[user_id] = data
    _ask_product_type_common_code(message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_image_no")
def handle_product_type_image_no(call):
    """Rasm talab qilinmadi"""
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    
    data["product_type_image_id"] = None
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_type_common_code(call.message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_common_code_yes")
def handle_product_type_common_code_yes(call):
    data = user_states.get(call.from_user.id, {})
    data["action"] = "waiting_product_type_common_code"
    user_states[call.from_user.id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "✍️ Umumiy kodni kiriting:",
        reply_markup=back_button("product_type_image_cancel"),
    )

@bot.callback_query_handler(func=lambda call: call.data == "product_type_common_code_no")
def handle_product_type_common_code_no(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    db = get_db()
    warehouse = data.get("warehouse")
    branch = data.get("branch", "common")
    added = db.add_product_type(
        data.get("product_type_name"),
        data.get("product_type_image_id"),
        warehouse,
        branch,
        None,
    )
    
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    
    if not added:
        user_states[user_id] = {
            "action": "waiting_product_type_name",
            "warehouse": warehouse,
            "branch": branch,
        }
        bot.send_message(
            call.message.chat.id,
            f"⚠️ '{data.get('product_type_name')}' nomli tur oldin ishlatilgan.\n\n✍️ Boshqa tur nomini kiriting:",
            reply_markup=back_button(f"product_branch_select:{warehouse}:{branch}"),
        )
        return

    user_states.pop(user_id, None)
    
    bot.send_message(
        call.message.chat.id,
        f"✅ '{data.get('product_type_name')}' turi qo'shildi!",
        reply_markup=product_types_menu(warehouse, branch),
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "waiting_product_type_common_code")
def process_product_type_common_code(message):
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    code = message.text.strip()
    if not code:
        bot.send_message(message.chat.id, "❌ Kod bo'sh bo'lishi mumkin emas")
        return
    db = get_db()
    warehouse = data.get("warehouse")
    branch = data.get("branch", "common")
    added = db.add_product_type(
        data.get("product_type_name"),
        data.get("product_type_image_id"),
        warehouse,
        branch,
        code,
    )
    
    
    if not added:
        user_states[user_id] = {
            "action": "waiting_product_type_name",
            "warehouse": warehouse,
            "branch": branch,
        }
        bot.send_message(
            message.chat.id,
            f"⚠️ '{data.get('product_type_name')}' nomli tur oldin ishlatilgan.\n\n✍️ Boshqa tur nomini kiriting:",
            reply_markup=back_button(f"product_branch_select:{warehouse}:{branch}"),
        )
        return
    
    user_states.pop(user_id, None)
    
    bot.send_message(
       message.chat.id,
       f"✅ '{data.get('product_type_name')}' turi qo'shildi!\n🔢 Umumiy kod: <b>{code}</b>",
       reply_markup=product_types_menu(warehouse, branch),
       parse_mode="HTML",
   )

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_actions:"))
def handle_product_type_actions(call):
    """Mahsulot turi sozlamalari (tahrirlash/o'chirish/back)"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""

    user_states[call.from_user.id] = {"warehouse": warehouse, "branch": branch, "product_type": product_type}

    text = f"📦 <b>{product_type}</b>\n\nAmalni tanlang:"
    db = get_db()
    ptype = db.get_product_type_by_name(product_type, warehouse, branch)
    markup = product_type_actions_menu(warehouse, branch, product_type)

    if ptype and ptype.get("image_id"):
        try:
            bot.edit_message_media(
                media=telebot.types.InputMediaPhoto(ptype["image_id"], caption=text, parse_mode="HTML"),
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

        bot.send_photo(call.message.chat.id, ptype["image_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        return

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")


# ✅ PRODUCT TYPE SELECT - MAHSULOTLAR BO'LIMI
@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_select:"))
def handle_product_type_select(call):
    """Mahsulot turini tanlash"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    
    user_id = call.from_user.id
    user_states[user_id] = {"warehouse": warehouse, "branch": branch, "product_type": product_type}
    
    _show_products_by_type_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type)

# ✅ PRODUCT TYPE EDIT
@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_edit:"))
def handle_product_type_edit(call):
    """Mahsulot turini tahrirlash"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    
    user_id = call.from_user.id
    user_states[user_id] = {
        "action": "awaiting_product_type_name_decision",
        "old_name": product_type,
        "new_name": product_type,
        "warehouse": warehouse,
        "branch": branch
    }
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_type_name_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_type_name_no")
    )
    bot.send_message(call.message.chat.id, "✏️ Mahsulot turi nomini yangilaysizmi?", reply_markup=markup)


def _ask_product_type_image_decision(chat_id, user_id):
    data = user_states.get(user_id, {})
    old_name = data.get("old_name")
    new_name = data.get("new_name", old_name)
    db = get_db()
    ptype = db.get_product_type_by_name(old_name, data.get("warehouse"), data.get("branch"))
    has_image = bool(ptype and ptype.get("image_id"))
    data["had_image_before"] = has_image
    if has_image:
        data["action"] = "awaiting_image_update"
        yes_text = "✅ Ha"
        no_text = "⏭️ O'tkazish"
        prompt = f"📷 Rasmni yangilaysizmi?\n\n<b>{old_name}</b> → <b>{new_name}</b>"
        yes_cb = "product_type_update_image_yes"
        no_cb = "product_type_update_image_no"
    else:
        data["action"] = "awaiting_image_add"
        yes_text = "✅ Ha"
        no_text = "⏭️ O'tkazish"
        prompt = f"🖼️ Rasm qo'shasizmi?\n\n<b>{old_name}</b> → <b>{new_name}</b>"
        yes_cb = "product_type_add_image_yes"
        no_cb = "product_type_add_image_no"
    user_states[user_id] = data
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton(yes_text, callback_data=yes_cb),
        telebot.types.InlineKeyboardButton(no_text, callback_data=no_cb)
    )
    bot.send_message(chat_id, prompt, reply_markup=markup, parse_mode="HTML")


def _ask_product_type_code_decision(chat_id, user_id):
    data = user_states.get(user_id, {})
    db = get_db()
    ptype = db.get_product_type_by_name(data.get("old_name"), data.get("warehouse"), data.get("branch"))
    old_common_code = (ptype or {}).get("common_code")
    data["old_common_code"] = old_common_code
    data["action"] = "awaiting_product_type_code_decision"
    user_states[user_id] = data

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_type_code_edit_yes"),
        telebot.types.InlineKeyboardButton("⏭️ O'tkazish", callback_data="product_type_code_edit_no")
    )
    if old_common_code:
        text = f"🔢 Umumiy kodni yangilaysizmi?\n\nJoriy kod: <b>{old_common_code}</b>"
    else:
        text = "🔢 Umumiy kod qo'shasizmi?"
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


def _finalize_product_type_edit(chat_id, user_id):
    data = user_states.get(user_id, {})
    if not data:
        return
    db = get_db()
    old_name = data.get("old_name")
    new_name = data.get("new_name", old_name)
    warehouse = data.get("warehouse")
    branch = data.get("branch")
    image_id = data.get("new_image_id")
    new_common_code = data.get("new_common_code")
    old_common_code = data.get("old_common_code")

    updated = db.update_product_type(
        old_name,
        new_name,
        image_id,
        warehouse,
        branch,
        new_common_code
    )

    if new_common_code and new_common_code != old_common_code:
        db.update_products_code_by_type(new_name, new_common_code, warehouse, branch)

    user_states.pop(user_id, None)
    if updated or (new_common_code and new_common_code != old_common_code):
        bot.send_message(chat_id, f"✅ '{new_name}' turi yangilandi!", reply_markup=product_types_menu(warehouse, branch))
    else:
        bot.send_message(chat_id, "ℹ️ O'zgarish kiritilmadi.", reply_markup=product_types_menu(warehouse, branch))


@bot.callback_query_handler(func=lambda call: call.data == "product_type_name_yes")
def handle_product_type_name_yes(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_type_name_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["action"] = "editing_product_type_name_input"
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)

    bot.send_message(
        call.message.chat.id,
        "✍️ Yangi tur nomini kiriting:",
        reply_markup=back_button(f"product_type_back:{data['warehouse']}:{data['branch']}")
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_name_no")
def handle_product_type_name_no(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_type_name_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["new_name"] = data.get("old_name")
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_type_image_decision(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "editing_product_type_name_input")
def process_product_type_edit(message):
    """Mahsulot turi nomini o'zgartirish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    new_name = message.text.strip()
    
    if not new_name:
        bot.send_message(message.chat.id, "❌ Tur nomi bo'sh bo'lishi mumkin emas")
        return
    
    data["new_name"] = new_name
    user_states[user_id] = data
    _ask_product_type_image_decision(message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_update_image_yes")
def handle_product_type_update_image_yes(call):
    """Rasm yangilash"""
    user_id = call.from_user.id
    user_states[user_id]["action"] = "uploading_product_type_new_image"
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "📷 Yangi rasm yuboring:",
        reply_markup=back_button("product_type_cancel_edit")
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "uploading_product_type_new_image")
def process_product_type_new_image(message):
    """Yangi rasm saqlash va turi tahrirlash"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    
    data["new_image_id"] = message.photo[-1].file_id
    user_states[user_id] = data
    _ask_product_type_code_decision(message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_update_image_no")
def handle_product_type_update_image_no(call):
    """Rasim qoldirish"""
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    
    data["new_image_id"] = None
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_type_code_decision(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_type_add_image_yes")
def handle_product_type_add_image_yes(call):
    """Rasm qo'shish"""
    user_id = call.from_user.id
    user_states[user_id]["action"] = "uploading_product_type_add_image"
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "📷 Rasm yuboring:",
        reply_markup=back_button("product_type_cancel_edit")
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "uploading_product_type_add_image")
def process_product_type_add_image(message):
    """Rasm qo'shib turi tahrirlash"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    
    data["new_image_id"] = message.photo[-1].file_id
    user_states[user_id] = data
    _ask_product_type_code_decision(message.chat.id, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "product_type_add_image_no")
def handle_product_type_add_image_no(call):
    """Rasm qo'shmasdan tahrirlash"""
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    
    data["new_image_id"] = None
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_type_code_decision(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_type_code_edit_yes")
def handle_product_type_code_edit_yes(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_type_code_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["action"] = "waiting_product_type_new_common_code"
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "✍️ Yangi umumiy kodni kiriting:",
        reply_markup=back_button("product_type_cancel_edit"),
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_type_code_edit_no")
def handle_product_type_code_edit_no(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_type_code_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _finalize_product_type_edit(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "waiting_product_type_new_common_code")
def process_product_type_new_common_code(message):
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    code = message.text.strip()
    if not code:
        bot.send_message(message.chat.id, "❌ Kod bo'sh bo'lishi mumkin emas")
        return
    data["new_common_code"] = code
    user_states[user_id] = data
    _finalize_product_type_edit(message.chat.id, user_id)

# ✅ PRODUCT TYPE DELETE
@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_delete:"))
def handle_product_type_delete(call):
    """Mahsulot turini o'chirishni tasdiqlash oynasi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"product_type_delete_confirm:{warehouse}:{branch}:{product_type}"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data=f"product_type_delete_cancel:{warehouse}:{branch}:{product_type}"),
    )

    confirm_text = f"⚠️ <b>{product_type}</b> turini o'chirasizmi?"
    try:
        bot.edit_message_caption(
            caption=confirm_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
        return
    except Exception:
        pass

    try:
        bot.edit_message_text(
            confirm_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        bot.send_message(
            call.message.chat.id,
            confirm_text,
            reply_markup=markup,
            parse_mode="HTML",
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_delete_confirm:"))
def handle_product_type_delete_confirm(call):
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""

    user_states.pop(call.from_user.id, None)
    
    db = get_db()
    db.delete_product_type(product_type, warehouse, branch)
    
    _show_product_types_message(
        call.message.chat.id,
        call.message.message_id,
        warehouse,
        branch,
    )
    
@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_delete_cancel:"))
def handle_product_type_delete_cancel(call):
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""

    user_states[call.from_user.id] = {"warehouse": warehouse, "branch": branch, "product_type": product_type}
    text = f"📦 <b>{product_type}</b>\n\nAmalni tanlang:"
    db = get_db()
    ptype = db.get_product_type_by_name(product_type, warehouse, branch)
    markup = product_type_actions_menu(warehouse, branch, product_type)
    if ptype and ptype.get("image_id"):
        try:
            bot.edit_message_media(
                media=telebot.types.InputMediaPhoto(ptype["image_id"], caption=text, parse_mode="HTML"),
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")



# ==================== PRODUCT HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_add:"))
def handle_product_add(call):
    """Mahsulot qo'shish"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    
    user_id = call.from_user.id
    user_states[user_id] = {
        "action": "adding_product",
        "warehouse": warehouse,
        "branch": branch,
        "product_type": product_type
    }
    
    bot.send_message(
        call.message.chat.id,
        MESSAGES["product_add_name"],
        reply_markup=back_button(f"product_type_back:{warehouse}:{branch}")
    )

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "adding_product")
def process_product_add_name(message):
    """Mahsulot nomini qabul qilish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    product_name = message.text.strip()
    
    if not product_name:
        bot.send_message(message.chat.id, "❌ Mahsulot nomi bo'sh bo'lishi mumkin emas")
        return
    
    data["product_name"] = product_name
    db = get_db()
    ptype = db.get_product_type_by_name(data.get("product_type"), data.get("warehouse"), data.get("branch"))
    common_code = ptype.get("common_code") if ptype else None
    if common_code:
        data["product_code"] = common_code
        if ptype and ptype.get("image_id"):
            data["product_image_id"] = None
            _ask_or_apply_product_unit(message.chat.id, user_id, data)
            return
        data["action"] = "awaiting_product_image_decision"
        user_states[user_id] = data
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_image_yes"),
            telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_image_no")
        )
        bot.send_message(
            message.chat.id,
            f"📦 <b>{product_name}</b>\n🔢 Kod: <b>{common_code}</b> (tur kodi)\n\n🖼️ Bu mahsulot uchun rasm yuborasizmi?",
            reply_markup=markup,
            parse_mode="HTML"
        )
        return
    data["action"] = "adding_product_code"
    user_states[user_id] = data
    
    bot.send_message(
        message.chat.id,
        f"📦 <b>{product_name}</b>\n\n🔢 Mahsulot kodini kiriting:\n(Masalan: SKL-001)",
        reply_markup=back_button(f"product_type_back:{data['warehouse']}:{data['branch']}"),
        parse_mode="HTML"
    )

def _show_product_add_confirmation(chat_id, data):
    """Mahsulot qo'shish yakuniy tasdiqlash oynasi"""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Tasdiq", callback_data="product_confirm_add"),
        telebot.types.InlineKeyboardButton("❌ Bekor", callback_data=f"product_type_back:{data['warehouse']}:{data['branch']}")
    )

    image_status = "✅ Bor" if data.get("product_image_id") else "❌ Yo'q"
    bot.send_message(
        chat_id,
        f"✅ Tasdiqlansinmi?\n\n📦 <b>{data['product_name']}</b>\n🔢 Kod: <b>{data['product_code']}</b>\n📏 Birlik: <b>{data.get('product_unit', 'dona')}</b>\n🖼️ Rasm: <b>{image_status}</b>",
        reply_markup=markup,
        parse_mode="HTML"
    )

def _ask_or_apply_product_unit(chat_id, user_id, data):
    db = get_db()
    units = db.get_all_units()
    if not units:
        data["product_unit"] = "dona"
        data["action"] = "added_product_confirm"
        user_states[user_id] = data
        _show_product_add_confirmation(chat_id, data)
        return
    data["action"] = "waiting_product_unit"
    user_states[user_id] = data
    markup = units_choose_menu("product_unit_select")
    markup.add(telebot.types.InlineKeyboardButton(MESSAGES["button_back"], callback_data=f"product_type_back:{data['warehouse']}:{data['branch']}"))
    bot.send_message(chat_id, "📏 Mahsulot birligini tanlang:", reply_markup=markup)

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "adding_product_code")
def process_product_code(message):
    """Mahsulot kodini qabul qilish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    
    code = message.text.strip()
    
    if not code:
        bot.send_message(message.chat.id, "❌ Mahsulot kodi bo'sh bo'lishi mumkin emas")
        return
    
    data["product_code"] = code
    db = get_db()
    ptype = db.get_product_type_by_name(data.get("product_type"), data.get("warehouse"), data.get("branch"))

    if ptype and ptype.get("image_id"):
       data["product_image_id"] = None
       _ask_or_apply_product_unit(message.chat.id, user_id, data)
       return

    data["action"] = "awaiting_product_image_decision"
    user_states[user_id] = data
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_image_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_image_no")
    )
    
    bot.send_message(
        message.chat.id,
        f"📦 <b>{data['product_name']}</b>\n🔢 Kod: <b>{code}</b>\n\n🖼️ Bu mahsulot uchun rasm yuborasizmi?",
        reply_markup=markup,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data == "product_image_yes")
def handle_product_image_yes(call):
    """Mahsulot rasmi yuklash bosqichi"""
    user_id = call.from_user.id
    bot.delete_message(call.message.chat.id, call.message.message_id)
    data = user_states.get(user_id, {})
    
    if data.get("action") != "awaiting_product_image_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return

    data["action"] = "uploading_product_image"
    user_states[user_id] = data

    bot.send_message(
        call.message.chat.id,
        MESSAGES["product_send_image"],
        reply_markup=back_button(f"product_type_back:{data['warehouse']}:{data['branch']}")
    )


@bot.callback_query_handler(func=lambda call: call.data == "product_image_no")
def handle_product_image_no(call):
    """Mahsulotni rasmsiz davom ettirish"""
    user_id = call.from_user.id
    bot.delete_message(call.message.chat.id, call.message.message_id)
    data = user_states.get(user_id, {})

    if data.get("action") != "awaiting_product_image_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return

    data["product_image_id"] = None
    _ask_or_apply_product_unit(call.message.chat.id, user_id, data)


@bot.message_handler(content_types=['photo'], func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "uploading_product_image")
def process_product_image(message):
    """Mahsulot rasmi qabul qilish"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})

    data["product_image_id"] = message.photo[-1].file_id
    _ask_or_apply_product_unit(message.chat.id, user_id, data)

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_unit_select:"))
def handle_product_unit_select(call):
    unit_name = call.data.split(":", 1)[1]
    data = user_states.get(call.from_user.id, {})
    if data.get("action") != "waiting_product_unit":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["product_unit"] = unit_name
    data["action"] = "added_product_confirm"
    user_states[call.from_user.id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _show_product_add_confirmation(call.message.chat.id, data)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "product_confirm_add")
def handle_product_confirm_add(call):
    """Mahsulotni qo'shish tasdiqlash"""
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    
    db = get_db()
    warehouse = data.get("warehouse")
    branch = data.get("branch")
    product_type = data.get("product_type")
    added = db.add_product(
        data.get("product_name"),
        data.get("product_code"),
        product_type,
        warehouse,
        branch,
        data.get("product_image_id"),
        data.get("product_unit", "dona"),
    )
    
    if not added:
        user_states[user_id] = {
            "action": "adding_product",
            "warehouse": warehouse,
            "branch": branch,
            "product_type": product_type,
        }
        bot.send_message(
            call.message.chat.id,
            f"⚠️ '{data.get('product_name')}' nomli mahsulot oldin ishlatilgan.\n\n✍️ Boshqa mahsulot nomini kiriting:",
            reply_markup=back_button(f"product_type_back:{warehouse}:{branch}"),
        )
        return
    
    user_states.pop(user_id, None)
    
    _show_products_by_type_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type)


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_select:"))
def handle_product_select(call):
    """Mahsulot nomi bosilganda detal oynasi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    product_name = parts[4] if len(parts) > 4 else ""

    user_states[call.from_user.id] = {
        "warehouse": warehouse,
        "branch": branch,
        "product_type": product_type,
        "product_name": product_name,
    }

    _show_product_details_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type, product_name)


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_edit:"))
def handle_product_edit(call):
    """Mahsulotni tahrirlash jarayonini boshlash"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    product_name = parts[4] if len(parts) > 4 else ""
    db = get_db()
    product = db.get_product_by_name(product_name, warehouse, branch, product_type) or {}
    
    user_states[call.from_user.id] = {
        "action": "awaiting_product_name_decision",
        "warehouse": warehouse,
        "branch": branch,
        "product_type": product_type,
        "old_product_name": product_name,
        "old_product_code": product.get("code", ""),
        "new_product_name": product_name,
    }
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_edit_name_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_edit_name_no"),
    )
    bot.send_message(call.message.chat.id, "✏️ Mahsulot nomini yangilaysizmi?", reply_markup=markup)

def _ask_product_new_code(chat_id, data):
    data["action"] = "editing_product_code"
    user_states[data.get("user_id")] = data
    bot.send_message(
        chat_id,
        f"🔢 Yangi mahsulot kodini kiriting:\n\nNom: <b>{data.get('new_product_name')}</b>",
        reply_markup=back_button(
            f"product_select:{data['warehouse']}:{data['branch']}:{data['product_type']}:{data['old_product_name']}"
        ),
        parse_mode="HTML",
    )

def _ask_product_code_update_decision(chat_id, data):
    data["action"] = "awaiting_product_code_decision"
    user_states[data.get("user_id")] = data
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_edit_code_yes"),
        telebot.types.InlineKeyboardButton("⏭ O'tkazish", callback_data="product_edit_code_skip"),
    )
    bot.send_message(chat_id, "🔢 Mahsulot kodini yangilaysizmi?", reply_markup=markup)


def _ask_product_unit_change(chat_id, user_id):
    data = user_states.get(user_id, {})
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_edit_unit_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_edit_unit_no"),
    )
    bot.send_message(chat_id, "📏 Mahsulot birligi o'zgaradimi?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_name_yes")
def handle_product_edit_name_yes(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_name_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["action"] = "editing_product_name_input"
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)

    bot.send_message(
        call.message.chat.id,
        f"✍️ Yangi mahsulot nomini kiriting:\n\nEski nom: <b>{data['old_product_name']}</b>",
        reply_markup=back_button(f"product_select:{data['warehouse']}:{data['branch']}:{data['product_type']}:{data['old_product_name']}"),
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "product_edit_name_no")
def handle_product_edit_name_no(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_name_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["new_product_name"] = data.get("old_product_name")
    data["user_id"] = user_id
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_code_update_decision(call.message.chat.id, data)
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "editing_product_name_input")
def process_product_edit_name(message):
    """Mahsulot tahriri uchun yangi nom"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    new_name = message.text.strip()

    if not new_name:
        bot.send_message(message.chat.id, "❌ Mahsulot nomi bo'sh bo'lishi mumkin emas")
        return

    data["new_product_name"] = new_name
    data["user_id"] = user_id
    user_states[user_id] = data

    _ask_product_code_update_decision(message.chat.id, data)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_code_yes")
def handle_product_edit_code_yes(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_code_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_new_code(call.message.chat.id, data)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_code_skip")
def handle_product_edit_code_skip(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "awaiting_product_code_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["new_product_code"] = data.get("old_product_code", "")
    data["new_product_unit"] = data.get("new_product_unit", "dona")
    user_states[user_id] = data
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _ask_product_unit_change(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)



@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "editing_product_code")
def process_product_edit_code(message):
    """Mahsulot tahriri uchun yangi kod"""
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    new_code = message.text.strip()

    if not new_code:
        bot.send_message(message.chat.id, "❌ Mahsulot kodi bo'sh bo'lishi mumkin emas")
        return

    data["new_product_code"] = new_code
    db = get_db()

    old_product = db.get_product_by_name(
        data.get("old_product_name"), data.get("warehouse"), data.get("branch"), data.get("product_type")
    )
    data["new_product_unit"] = (old_product or {}).get("unit", "dona")
    user_states[user_id] = data

    _ask_product_unit_change(message.chat.id, user_id)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_unit_yes")
def handle_product_edit_unit_yes(call):
    data = user_states.get(call.from_user.id, {})
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    db = get_db()
    units = db.get_all_units()
    if not units:
        data["new_product_unit"] = "dona"
        user_states[call.from_user.id] = data
        bot.answer_callback_query(call.id, "Birliklar ro'yxati bo'sh. 'dona' saqlandi.")
        _continue_product_edit_after_unit(call.message.chat.id, call.from_user.id)
        return
    markup = units_choose_menu("product_edit_unit_select")
    markup.add(
        telebot.types.InlineKeyboardButton(
            MESSAGES["button_back"],
            callback_data=f"product_select:{data['warehouse']}:{data['branch']}:{data['product_type']}:{data['old_product_name']}",
        )
    )
    data["action"] = "editing_product_choose_unit"
    user_states[call.from_user.id] = data
    bot.send_message(call.message.chat.id, "📏 Yangi birlikni tanlang:", reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_unit_no")
def handle_product_edit_unit_no(call):
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)
    _continue_product_edit_after_unit(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_edit_unit_select:"))
def handle_product_edit_unit_select(call):
    data = user_states.get(call.from_user.id, {})
    if data.get("action") != "editing_product_choose_unit":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["new_product_unit"] = call.data.split(":", 1)[1]
    user_states[call.from_user.id] = data
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)
    _continue_product_edit_after_unit(call.message.chat.id, call.from_user.id)


def _continue_product_edit_after_unit(chat_id, user_id):
    data = user_states.get(user_id, {})
    db = get_db()
    ptype = db.get_product_type_by_name(data.get("product_type"), data.get("warehouse"), data.get("branch"))
    if ptype and ptype.get("image_id"):
        updated = db.update_product(
            data.get("old_product_name"),
            data.get("new_product_name"),
            data.get("new_product_code"),
            data.get("warehouse"),
            data.get("branch"),
            data.get("product_type"),
            unit=data.get("new_product_unit", "dona"),
        )
        warehouse = data.get("warehouse")
        branch = data.get("branch")
        product_type = data.get("product_type")
        new_name = data.get("new_product_name")
        user_states.pop(user_id, None)
        if updated:
            bot.send_message(chat_id, "✅ Mahsulot muvaffaqiyatli yangilandi")
            _show_product_details_message(chat_id, 0, warehouse, branch, product_type, new_name)
        else:
            bot.send_message(chat_id, "❌ Tahrirlashda xatolik (nom/kod band bo'lishi mumkin)")
        return

    data["action"] = "editing_product_image_decision"
    user_states[user_id] = data
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data="product_edit_image_yes"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data="product_edit_image_no"),
    )
    bot.send_message(chat_id, "🖼️ Turda rasm yo'q.\nMahsulot rasmini yangilaysizmi?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_image_yes")
def handle_product_edit_image_yes(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "editing_product_image_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    data["action"] = "uploading_edited_product_image"
    user_states[user_id] = data
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "📷 Yangi rasm yuboring:",
        reply_markup=back_button(
            f"product_select:{data['warehouse']}:{data['branch']}:{data['product_type']}:{data['old_product_name']}"
        ),
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "product_edit_image_no")
def handle_product_edit_image_no(call):
    user_id = call.from_user.id
    data = user_states.get(user_id, {})
    if data.get("action") != "editing_product_image_decision":
        bot.answer_callback_query(call.id, "Holat topilmadi", show_alert=True)
        return
    db = get_db()
    updated = db.update_product(
        data.get("old_product_name"),
        data.get("new_product_name"),
        data.get("new_product_code"),
        data.get("warehouse"),
        data.get("branch"),
        data.get("product_type"),
        unit=data.get("new_product_unit", "dona"),
    )
    
    warehouse = data.get("warehouse")
    branch = data.get("branch")
    product_type = data.get("product_type")
    new_name = data.get("new_product_name")

    user_states.pop(user_id, None)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    if updated:
        bot.send_message(call.message.chat.id, "✅ Mahsulot muvaffaqiyatli yangilandi")
        _show_product_details_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type, new_name)
    else:
        bot.send_message(call.message.chat.id, "❌ Tahrirlashda xatolik (nom/kod band bo'lishi mumkin)")
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda message: user_states.get(message.from_user.id, {}).get("action") == "uploading_edited_product_image")
def process_edited_product_image(message):
    user_id = message.from_user.id
    data = user_states.get(user_id, {})
    db = get_db()
    updated = db.update_product(
        data.get("old_product_name"),
        data.get("new_product_name"),
        data.get("new_product_code"),
        data.get("warehouse"),
        data.get("branch"),
        data.get("product_type"),
        message.photo[-1].file_id,
        data.get("new_product_unit", "dona"),
    )
    warehouse = data.get("warehouse")
    branch = data.get("branch")
    product_type = data.get("product_type")
    new_name = data.get("new_product_name")
    user_states.pop(user_id, None)

    if updated:
        bot.send_message(message.chat.id, "✅ Mahsulot rasmi bilan yangilandi")
        _show_product_details_message(message.chat.id, message.message_id, warehouse, branch, product_type, new_name)
    else:
        bot.send_message(message.chat.id, "❌ Tahrirlashda xatolik (nom/kod band bo'lishi mumkin)")


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_delete:"))
def handle_product_delete(call):
    """Mahsulotni o'chirishni tasdiqlash oynasi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    product_name = parts[4] if len(parts) > 4 else ""

    db = get_db()
    qty = db.get_inventory(product_name, warehouse, branch, product_type).get("quantity", 0)

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Ha", callback_data=f"product_delete_confirm:{warehouse}:{branch}:{product_type}:{product_name}"),
        telebot.types.InlineKeyboardButton("❌ Yo'q", callback_data=f"product_delete_cancel:{warehouse}:{branch}:{product_type}:{product_name}"),
    )

    text = f"⚠️ <b>{product_name}</b> o'chirilsinmi?\n\nSkladdagi qoldiq: <b>{qty}</b>"
    db_ptype = db.get_product_type_by_name(product_type, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type)
    image_id = _get_product_display_image(product, db_ptype)

    if image_id:
        try:
            bot.edit_message_media(
                media=telebot.types.InputMediaPhoto(image_id, caption=text, parse_mode="HTML"),
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_delete_confirm:"))
def handle_product_delete_confirm(call):
    """Mahsulotni tasdiqlab o'chirish"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""
    product_name = parts[4] if len(parts) > 4 else ""

    db = get_db()
    db.delete_product(product_name, warehouse, branch, product_type)

    _show_products_by_type_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type)


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_delete_cancel:"))
def handle_product_delete_cancel(call):
    """Mahsulotni o'chirish bekor qilindi"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""

    _show_products_by_type_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type)

# ==================== BACK HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data == "warehouse_list")
def handle_warehouse_list_back(call):
    """Sklad ro'yxatiga qaytish"""
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    bot.edit_message_text(
        "👤 Salom, Administrator!\n\nIshlash uchun skladni tanlang:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=warehouse_list_menu()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_back:"))
def handle_admin_back(call):
    """Admin panelga qaytish"""
    warehouse = call.data.split(":")[1]
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    bot.edit_message_text(
        f"👤 Salom, Administrator!\n\n🏭 Sklad: <b>{warehouse}</b>\n\nIshlash uchun tugmani tanlang:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=admin_main_menu(warehouse),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_home:"))
def handle_admin_home(call):
    """Admin uchun Asosiy: eski xabarni o'chirib asosiy sahifani yangi xabar qilib yuborish."""
    warehouse = call.data.split(":", 1)[1]
    user_states.pop(call.from_user.id, None)
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        f"👤 Salom, Administrator!\n\n🏭 Sklad: <b>{warehouse}</b>\n\nIshlash uchun tugmani tanlang:",
        reply_markup=admin_main_menu(warehouse),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_type_back:"))
def handle_product_type_back(call):
    """Filial tanlashga qaytish"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    _show_product_types_message(call.message.chat.id, call.message.message_id, warehouse, branch)


@bot.callback_query_handler(func=lambda call: call.data.startswith("product_list_back:"))
def handle_product_list_back(call):
    """Mahsulot detal oynasidan ro'yxatga qaytish"""
    parts = call.data.split(":")
    warehouse = parts[1]
    branch = parts[2] if len(parts) > 2 else "common"
    product_type = parts[3] if len(parts) > 3 else ""

    user_states.pop(call.from_user.id, None)
    _show_products_by_type_message(call.message.chat.id, call.message.message_id, warehouse, branch, product_type)


@bot.callback_query_handler(func=lambda call: call.data == "product_type_image_cancel")
def handle_product_type_image_cancel(call):
    """Tur qo'shishda rasm yuborishni bekor qilish"""
    data = user_states.get(call.from_user.id, {})
    warehouse = data.get("warehouse")
    branch = data.get("branch", "common")
    user_states.pop(call.from_user.id, None)
    _show_product_types_message(call.message.chat.id, call.message.message_id, warehouse, branch)


@bot.callback_query_handler(func=lambda call: call.data == "product_type_cancel_edit")
def handle_product_type_cancel_edit(call):
    """Tur tahrirlashda rasm bosqichini bekor qilish"""
    data = user_states.get(call.from_user.id, {})
    warehouse = data.get("warehouse")
    branch = data.get("branch", "common")
    user_states.pop(call.from_user.id, None)
    _show_product_types_message(call.message.chat.id, call.message.message_id, warehouse, branch)

@bot.callback_query_handler(func=lambda call: call.data.startswith("product_branch_back:"))
def handle_product_branch_back(call):
    """Mahsulot bo'limiga qaytish"""
    warehouse = call.data.split(":")[1]
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    try:
        bot.edit_message_text(
            "🏢 Filial tanlang yoki Umumiy:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=branches_selection_menu(warehouse),
            parse_mode="HTML"
        )
    except Exception:
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            "🏢 Filial tanlang yoki Umumiy:",
            reply_markup=branches_selection_menu(warehouse),
            parse_mode="HTML"
        )

# ==================== USER FLOW HELPERS ====================

def _user_state(user_id):
    state = user_states.get(user_id)
    return state if isinstance(state, dict) else {}

def _set_user_state(user_id, **kwargs):
    state = _user_state(user_id).copy()
    state.update(kwargs)
    user_states[user_id] = state
    return state

def _clear_user_action(user_id):
    state = _user_state(user_id).copy()
    warehouse = state.get("warehouse")
    user_states[user_id] = {"warehouse": warehouse} if warehouse else {}

def _is_admin_list_flow(user_id):
    state = _user_state(user_id)
    return user_id == ADMIN_ID and state.get("list_owner") == "admin"

def _display_actor_name(username, first_name=None):
    if username and username != "NoUsername":
        return f"@{username}"
    return first_name or "Foydalanuvchi"

def _branch_title(branch):
    return "🌍 Umumiy bo'lim" if branch == "common" else f"🏢 {branch}"

def _get_user_flow_image(product, product_type):
    if product_type and product_type.get("image_id"):
        return product_type["image_id"]
    if product and product.get("image_id"):
        return product["image_id"]
    return None

def _get_product_unit(db, warehouse, branch, product_type_name, product_name, default="dona"):
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    if not product:
        return default
    return product.get("unit", default)

def _show_message_with_optional_photo(chat_id, text, markup=None, image_id=None, message_id=None, parse_mode="HTML"):
    if image_id:
        if message_id:
            try:
                bot.edit_message_media(
                    media=telebot.types.InputMediaPhoto(image_id, caption=text, parse_mode=parse_mode),
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                )
                return message_id
            except Exception:
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
        sent = bot.send_photo(chat_id, image_id, caption=text, reply_markup=markup, parse_mode=parse_mode)
        return sent.message_id

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode=parse_mode)
            return message_id
        except Exception:
            try:
                bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode=parse_mode)
                return message_id
            except Exception:
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
    sent = bot.send_message(chat_id, text, reply_markup=markup, parse_mode=parse_mode)
    return sent.message_id

def _show_user_main(chat_id, warehouse, message_id=None):
    text = f"🏭 <b>{warehouse}</b>\n\nKerakli bo'limni tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=user_main_menu(warehouse),
        message_id=message_id,
    )

def _show_user_branches(chat_id, warehouse, action, message_id=None):
    action_title = "kiritish" if action == "input" else "chiqarish"
    text = f"🏭 <b>{warehouse}</b>\n\nMahsulot {action_title} uchun bo'limni tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=branches_menu_user(warehouse, action),
        message_id=message_id,
    )

def _show_user_types(chat_id, warehouse, branch, action, message_id=None):
    text = f"{_branch_title(branch)}\n\nMahsulot turini tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=product_types_menu_user(warehouse, branch, action),
        message_id=message_id,
    )

def _clear_message_buttons(chat_id, message_id):
    """Oldingi xabardagi inline tugmalarni olib tashlash."""
    try:
        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    except Exception:
        pass

def _clear_buttons_and_send_user_types(chat_id, warehouse, branch, action, message_id):
    """Mahsulot ro'yxati xabarini qoldirib, tugmalarini o'chiradi va mahsulot turlarini yangi xabar qilib yuboradi."""
    _clear_message_buttons(chat_id, message_id)
    return _show_user_types(chat_id, warehouse, branch, action)

def _show_user_products(chat_id, warehouse, branch, product_type_name, action, message_id=None):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    image_id = ptype.get("image_id") if ptype else None
    text = f"{_branch_title(branch)}\n📦 <b>{product_type_name}</b>\n\nMahsulotni tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=products_by_type_menu_user(warehouse, branch, product_type_name, action),
        image_id=image_id,
        message_id=message_id,
    )

def _show_list_branches(chat_id, warehouse, message_id=None, is_admin=False):
    text = f"🏭 <b>{warehouse}</b>\n\nRo'yxat uchun bo'limni tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=list_branches_menu(warehouse, is_admin=is_admin),
        message_id=message_id,
    )

def _show_list_types(chat_id, warehouse, branch, message_id=None):
    text = f"{_branch_title(branch)}\n\nMahsulot turini tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=product_types_menu_user(warehouse, branch, "list"),
        message_id=message_id,
    )

def _show_list_products(chat_id, warehouse, branch, product_type_name, message_id=None):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    image_id = ptype.get("image_id") if ptype else None
    text = f"{_branch_title(branch)}\n📦 <b>{product_type_name}</b>\n\nMahsulotni tanlang:"
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=products_by_type_menu_user(warehouse, branch, product_type_name, "list"),
        image_id=image_id,
        message_id=message_id,
    )

def _show_list_product_details(chat_id, warehouse, branch, product_type_name, product_name, message_id=None):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    qty = db.get_inventory(product_name, warehouse, branch, product_type_name).get("quantity", 0)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    image_id = _get_product_display_image(product, ptype)
    text = (
        f"{_branch_title(branch)}\n"
        f"🗂️ Turi: <b>{product_type_name}</b>\n"
        f"📦 Mahsulot: <b>{product_name}</b>\n"
        f"📊 Skladda bor: <b>{qty}</b> {unit}\n\n"
        "Shu turdagi mahsulotlar:"
    )
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=products_by_type_menu_user(warehouse, branch, product_type_name, "list"),
        image_id=image_id,
        message_id=message_id,
    )

def _show_user_input_prompt(chat_id, warehouse, branch, product_type_name, product_name):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    qty = db.get_inventory(product_name, warehouse, branch, product_type_name).get("quantity", 0)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    image_id = _get_user_flow_image(product, ptype)
    text = (
        f"📦 <b>{product_name}</b>\n"
        f"{_branch_title(branch)}\n"
        f"📊 Skladda bor: <b>{qty}</b> {unit}\n\n"
        "Kiritiladigan miqdorni yuboring:"
    )
    sent_id = _show_message_with_optional_photo(
        chat_id,
        text,
        markup=input_quantity_back_menu(warehouse, branch, product_type_name),
        image_id=image_id,
    )
    return sent_id, qty

def _show_user_remove_prompt(chat_id, warehouse, branch, product_type_name, product_name):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    qty = db.get_inventory(product_name, warehouse, branch, product_type_name).get("quantity", 0)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    image_id = _get_user_flow_image(product, ptype)
    text = (
        f"📦 <b>{product_name}</b>\n"
        f"{_branch_title(branch)}\n"
        f"📊 Skladda bor: <b>{qty}</b> {unit}\n\n"
        "Chiqariladigan miqdorni yuboring:"
    )
    sent_id = _show_message_with_optional_photo(
        chat_id,
        text,
        markup=remove_quantity_back_menu(warehouse, branch, product_type_name),
        image_id=image_id,
    )
    return sent_id, qty

def _send_user_input_result(chat_id, warehouse, branch, product_type_name, product_name, quantity, total_quantity):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    image_id = _get_user_flow_image(product, ptype)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    text = (
        f"📦 <b>{product_name}</b>\n"
        f"{_branch_title(branch)}\n"
        f"🗂️ Turi: <b>{product_type_name}</b>\n"
        f"➕ Qo'shildi: <b>{quantity}</b> {unit}\n"
        f"📊 Jami: <b>{total_quantity}</b> {unit}\n\n"
        "Yana mahsulot tanlashingiz mumkin:"
    )
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=products_by_type_menu_user(warehouse, branch, product_type_name, "input"),
        image_id=image_id,
    )

def _notify_groups_about_inventory_change(user, warehouse, branch, product_type_name, product_name, quantity, total_quantity, action, description=None):
    db = get_db()
    groups = db.get_warehouse_groups(warehouse)
    if not groups:
        return

    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    image_id = _get_user_flow_image(product, ptype)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    username = _display_actor_name(user.username, getattr(user, "first_name", None))
    change_line = "➕ Kirim" if action == "input" else "➖ Chiqim"
    description_text = f"\n📝 Tavsif: <blockquote>{description}</blockquote>" if description else ""
    text = (
        f"📦 <b>{product_name}</b>\n"
        f"🏭 Sklad: <b>{warehouse}</b>\n"
        f"{_branch_title(branch)}\n"
        f"🗂️ Turi: <b>{product_type_name}</b>\n\n"
        f"{change_line}: <b>{quantity}</b> {unit}\n"
        f"📊 Joriy qoldiq: <b>{total_quantity}</b> {unit}{description_text}\n\n"
        f"👤 {username}\n"
        f"🆔 <code>{user.id}</code>"
    )
    for group in groups:
        group_id = group.get("group_id")
        if not group_id:
            continue
        try:
            if image_id:
                bot.send_photo(group_id, image_id, caption=text, parse_mode="HTML")
            else:
                bot.send_message(group_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Guruhga yuborib bo'lmadi ({group_id}): {e}")

def _send_user_remove_result(chat_id, warehouse, branch, product_type_name, product_name, quantity, total_quantity, description=None):
    db = get_db()
    ptype = db.get_product_type_by_name(product_type_name, warehouse, branch)
    product = db.get_product_by_name(product_name, warehouse, branch, product_type_name)
    image_id = _get_user_flow_image(product, ptype)
    unit = _get_product_unit(db, warehouse, branch, product_type_name, product_name)
    description_block = f"\n<blockquote>{description}</blockquote>\n" if description else "\n"
    text = (
        f"📦 <b>{product_name}</b>{description_block}"
        f"{_branch_title(branch)}\n"
        f"🗂️ Turi: <b>{product_type_name}</b>\n"
        f"➖ Chiqarildi: <b>{quantity}</b> {unit}\n"
        f"📊 Hozirgi qoldiq: <b>{total_quantity}</b> {unit}\n\n"
        "Yana mahsulot tanlashingiz mumkin:"
    )
    return _show_message_with_optional_photo(
        chat_id,
        text,
        markup=products_by_type_menu_user(warehouse, branch, product_type_name, "remove"),
        image_id=image_id,
    )

def _complete_remove_without_description(chat_id, user_id, warehouse, branch, product_type_name, product_name, quantity):
    db = get_db()
    new_quantity = db.remove_inventory(product_name, quantity, warehouse, branch, product_type_name)
    result_message_id = _send_user_remove_result(
        chat_id, warehouse, branch, product_type_name, product_name, quantity, new_quantity, None
    )
    _set_user_state(
        user_id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        action=None,
        menu_message_id=result_message_id,
    )
    user = bot.get_chat(user_id)
    _notify_groups_about_inventory_change(
        user, warehouse, branch, product_type_name, product_name, quantity, new_quantity, "remove"
    )

# ==================== USER HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_warehouse:"))
def handle_user_warehouse_select(call):
    warehouse = call.data.split(":", 1)[1]
    _set_user_state(call.from_user.id, warehouse=warehouse, action=None)
    bot.answer_callback_query(call.id)
    _show_user_main(call.message.chat.id, warehouse, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_main:"))
def handle_user_main_with_warehouse(call):
    warehouse = call.data.split(":", 1)[1]
    db = get_db()
    user_id = call.from_user.id
    user = db.get_user(user_id)
    _clear_user_action(user_id)
    bot.answer_callback_query(call.id)
    if user_id == ADMIN_ID or not user:
        bot.edit_message_text(
            f"👤 Salom, Administrator!\n\n🏭 Sklad: <b>{warehouse}</b>\n\nIshlash uchun tugmani tanlang:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_main_menu(warehouse),
            parse_mode="HTML",
        )
        return
    _show_user_main(call.message.chat.id, warehouse, call.message.message_id)

 #==== User Asosiy tugma orqali qaytsa ===== 
@bot.callback_query_handler(func=lambda call: call.data.startswith("user_home:"))
def handle_user_home(call):
    """Foydalanuvchi uchun Asosiy: eski xabarni o'chirib asosiy sahifani qayta yuborish."""
    warehouse = call.data.split(":", 1)[1]
    db = get_db()
    user_id = call.from_user.id
    user = db.get_user(user_id)
    _set_user_state(user_id, warehouse=warehouse, action=None)
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    if user_id == ADMIN_ID or not user:
        bot.send_message(
            call.message.chat.id,
            f"👤 Salom, Administrator!\n\n🏭 Sklad: <b>{warehouse}</b>\n\nIshlash uchun tugmani tanlang:",
            reply_markup=admin_main_menu(warehouse),
            parse_mode="HTML",
        )
    else:
        _show_user_main(call.message.chat.id, warehouse)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input:"))
def handle_user_input(call):
    warehouse = call.data.split(":", 1)[1]
    _set_user_state(call.from_user.id, warehouse=warehouse, action="user_input")
    bot.answer_callback_query(call.id)
    _show_user_branches(call.message.chat.id, warehouse, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove:") and not call.data.startswith("user_remove_desc_"))
def handle_user_remove(call):
    warehouse = call.data.split(":", 1)[1]
    _set_user_state(call.from_user.id, warehouse=warehouse, action="user_remove")
    bot.answer_callback_query(call.id)
    _show_user_branches(call.message.chat.id, warehouse, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_list:"))
def handle_user_list(call):
    warehouse = call.data.split(":", 1)[1]
    _set_user_state(call.from_user.id, warehouse=warehouse, action="user_list", list_owner="user")
    bot.answer_callback_query(call.id)
    _show_list_branches(call.message.chat.id, warehouse, call.message.message_id, is_admin=False)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_list:"))
def handle_admin_list(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    warehouse = call.data.split(":", 1)[1]
    _set_user_state(call.from_user.id, warehouse=warehouse, action="admin_list", list_owner="admin")
    bot.answer_callback_query(call.id)
    _show_list_branches(call.message.chat.id, warehouse, call.message.message_id, is_admin=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_list_soon:"))
def handle_admin_list_soon(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    bot.answer_callback_query(
        call.id,
        "Bu funksiyalar jarayonda, Tez orada qo'shiladi..",
        show_alert=True,
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_branches:"))
def handle_user_input_branches_back(call):
    warehouse = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)
    _show_user_branches(call.message.chat.id, warehouse, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_branches:"))
def handle_user_remove_branches_back(call):
    warehouse = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)
    _show_user_branches(call.message.chat.id, warehouse, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_list_branches:"))
def handle_user_list_branches_back(call):
    warehouse = call.data.split(":", 1)[1]
    is_admin = _is_admin_list_flow(call.from_user.id)
    bot.answer_callback_query(call.id)
    _show_list_branches(call.message.chat.id, warehouse, call.message.message_id, is_admin=is_admin)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_products:"))
def handle_user_input_products_back(call):
    _, warehouse, branch, product_type_name = call.data.split(":", 3)
    bot.answer_callback_query(call.id)
    _show_user_products(call.message.chat.id, warehouse, branch, product_type_name, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_products:"))
def handle_user_remove_products_back(call):
    _, warehouse, branch, product_type_name = call.data.split(":", 3)
    bot.answer_callback_query(call.id)
    _show_user_products(call.message.chat.id, warehouse, branch, product_type_name, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_branch:"))
def handle_user_input_branch(call):
    _, warehouse, branch = call.data.split(":", 2)
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, action="user_input")
    bot.answer_callback_query(call.id)
    _show_user_types(call.message.chat.id, warehouse, branch, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_branch:"))
def handle_user_remove_branch(call):
    _, warehouse, branch = call.data.split(":", 2)
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, action="user_remove")
    bot.answer_callback_query(call.id)
    _show_user_types(call.message.chat.id, warehouse, branch, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_types:"))
def handle_user_input_types_back(call):
    _, warehouse, branch = call.data.split(":", 2)
    bot.answer_callback_query(call.id)
    _clear_buttons_and_send_user_types(call.message.chat.id, warehouse, branch, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_types:"))
def handle_user_remove_types_back(call):
    _, warehouse, branch = call.data.split(":", 2)
    bot.answer_callback_query(call.id)
    _clear_buttons_and_send_user_types(call.message.chat.id, warehouse, branch, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_type:"))
def handle_user_input_type(call):
    _, warehouse, branch, product_type_name = call.data.split(":", 3)
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, product_type=product_type_name, action="user_input")
    bot.answer_callback_query(call.id)
    _show_user_products(call.message.chat.id, warehouse, branch, product_type_name, "input", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_type:"))
def handle_user_remove_type(call):
    _, warehouse, branch, product_type_name = call.data.split(":", 3)
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, product_type=product_type_name, action="user_remove")
    bot.answer_callback_query(call.id)
    _show_user_products(call.message.chat.id, warehouse, branch, product_type_name, "remove", call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_input_product:"))
def handle_user_input_product(call):
    _, warehouse, branch, product_type_name, product_name = call.data.split(":", 4)
    _clear_message_buttons(call.message.chat.id, call.message.message_id)
    prompt_message_id, available_qty = _show_user_input_prompt(
       call.message.chat.id, warehouse, branch, product_type_name, product_name
    )
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        product_name=product_name,
        action="user_input_quantity",
        prompt_message_id=prompt_message_id,
        available_quantity=available_qty,
        menu_message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: _user_state(message.from_user.id).get("action") == "user_input_quantity")
def handle_user_input_quantity(message):
    user_id = message.from_user.id
    state = _user_state(user_id)
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            raise ValueError
    except Exception:
        bot.reply_to(message, MESSAGES["error_invalid_quantity"])
        return

    db = get_db()
    new_quantity = db.add_inventory(
        state["product_name"], quantity, state["warehouse"], state["branch"], state["product_type"]
    )

    try:
        bot.delete_message(message.chat.id, state.get("prompt_message_id"))
    except Exception:
        pass
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    result_message_id = _send_user_input_result(
        message.chat.id,
        state["warehouse"],
        state["branch"],
        state["product_type"],
        state["product_name"],
        quantity,
        new_quantity,
    )
    _notify_groups_about_inventory_change(
        message.from_user, state["warehouse"], state["branch"], state["product_type"], state["product_name"],
        quantity, new_quantity, "input"
    )
    
    _set_user_state(
        user_id,
        warehouse=state["warehouse"],
        branch=state["branch"],
        product_type=state["product_type"],
        action=None,
        menu_message_id=result_message_id,
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_product:"))
def handle_user_remove_product(call):
    _, warehouse, branch, product_type_name, product_name = call.data.split(":", 4)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    prompt_message_id, available_qty = _show_user_remove_prompt(
        call.message.chat.id, warehouse, branch, product_type_name, product_name
    )
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        product_name=product_name,
        action="user_remove_quantity",
        prompt_message_id=prompt_message_id,
        available_quantity=available_qty,
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: _user_state(message.from_user.id).get("action") == "user_remove_quantity")
def handle_user_remove_quantity(message):
    user_id = message.from_user.id
    state = _user_state(user_id)
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            raise ValueError
    except Exception:
        bot.reply_to(message, MESSAGES["error_invalid_quantity"])
        return

    available_qty = state.get("available_quantity", 0)
    db = get_db()
    unit = _get_product_unit(
        db, state["warehouse"], state["branch"], state["product_type"], state["product_name"]
    )
    if quantity > available_qty:
        bot.reply_to(message, f"❌ Skladda faqat {available_qty} {unit} mavjud.")
        return

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    prompt_id = state.get("prompt_message_id")
    if prompt_id:
        _show_message_with_optional_photo(
            message.chat.id,
            (
                f"📦 <b>{state['product_name']}</b>\n"
                f"➖ Chiqariladi: <b>{quantity}</b> {unit}\n\n"
                "Tavsif kiritilsinmi?"
            ),
            markup=remove_description_menu(
                state["warehouse"], state["branch"], state["product_type"], state["product_name"], quantity
            ),
            message_id=prompt_id,
        )
    _set_user_state(
        user_id,
        warehouse=state["warehouse"],
        branch=state["branch"],
        product_type=state["product_type"],
        product_name=state["product_name"],
        action="user_remove_waiting_description_choice",
        prompt_message_id=prompt_id,
        remove_quantity=quantity,
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_desc_no:"))
def handle_user_remove_desc_no(call):
    _, warehouse, branch, product_type_name, product_name, quantity = call.data.split(":", 5)
    if branch == "common":
        _show_message_with_optional_photo(
            call.message.chat.id,
            (
                f"📦 <b>{product_name}</b>\n"
                "Tavsif o'rniga qaysi bo'limga chiqarilganini tanlang:"
            ),
            markup=remove_target_branch_menu(warehouse, product_type_name, product_name, quantity),
            message_id=call.message.message_id,
        )
        bot.answer_callback_query(call.id)
        return
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    _complete_remove_without_description(
        call.message.chat.id, call.from_user.id, warehouse, branch, product_type_name, product_name, int(quantity)
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_target_branch:"))
def handle_user_remove_target_branch(call):
    _, warehouse, target_branch, product_type_name, product_name, quantity = call.data.split(":", 5)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    db = get_db()
    new_quantity = db.remove_inventory(product_name, int(quantity), warehouse, "common", product_type_name)
    result_message_id = _send_user_remove_result(
        call.message.chat.id,
        warehouse,
        "common",
        product_type_name,
        product_name,
        int(quantity),
        new_quantity,
        f"Chiqim bo'limi: {_branch_title(target_branch)}",
    )
    _notify_groups_about_inventory_change(
        call.from_user, warehouse, "common", product_type_name, product_name, int(quantity), new_quantity, "remove",
        f"Chiqim bo'limi: {_branch_title(target_branch)}"
    )
    
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch="common",
        product_type=product_type_name,
        action=None,
        menu_message_id=result_message_id,
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_remove_desc_yes:"))
def handle_user_remove_desc_yes(call):
    _, warehouse, branch, product_type_name, product_name, quantity = call.data.split(":", 5)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    sent = bot.send_message(call.message.chat.id, f"➖ Chiqariladi: {product_name}\n\n✍️ Tavsifni matn ko'rinishida yuboring (Izoh):")
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        product_name=product_name,
        action="user_remove_description",
        remove_quantity=int(quantity),
        prompt_message_id=sent.message_id,
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: _user_state(message.from_user.id).get("action") == "user_remove_description")
def handle_user_remove_description(message):
    user_id = message.from_user.id
    state = _user_state(user_id)
    description = message.text.strip()
    db = get_db()
    new_quantity = db.remove_inventory(
        state["product_name"], state["remove_quantity"], state["warehouse"], state["branch"], state["product_type"]
    )

    try:
        bot.delete_message(message.chat.id, state.get("prompt_message_id"))
    except Exception:
        pass
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    result_message_id = _send_user_remove_result(
        message.chat.id,
        state["warehouse"],
        state["branch"],
        state["product_type"],
        state["product_name"],
        state["remove_quantity"],
        new_quantity,
        description,
    )
    _notify_groups_about_inventory_change(
        message.from_user, state["warehouse"], state["branch"], state["product_type"], state["product_name"],
        state["remove_quantity"], new_quantity, "remove", description
    )
    
    _set_user_state(
        user_id,
        warehouse=state["warehouse"],
        branch=state["branch"],
        product_type=state["product_type"],
        action=None,
        menu_message_id=result_message_id,
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("list_branch:"))
def handle_list_branch(call):
    _, warehouse, branch = call.data.split(":", 2)
    action = "admin_list" if _is_admin_list_flow(call.from_user.id) else "user_list"
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, action=action)
    _show_list_types(call.message.chat.id, warehouse, branch, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_list_types:"))
def handle_list_types_back(call):
    _, warehouse, branch = call.data.split(":", 2)
    action = "admin_list" if _is_admin_list_flow(call.from_user.id) else "user_list"
    _set_user_state(call.from_user.id, warehouse=warehouse, branch=branch, action=action)
    _safe_delete_message(call.message.chat.id, call.message.message_id)
    _show_list_types(call.message.chat.id, warehouse, branch)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_list_type:"))
def handle_list_type(call):
    _, warehouse, branch, product_type_name = call.data.split(":", 3)
    action = "admin_list" if _is_admin_list_flow(call.from_user.id) else "user_list"
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        action= action,
    )
    _show_list_products(call.message.chat.id, warehouse, branch, product_type_name, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_list_product:"))
def handle_list_product(call):
    _, warehouse, branch, product_type_name, product_name = call.data.split(":", 4)
    action = "admin_list" if _is_admin_list_flow(call.from_user.id) else "user_list"
    _set_user_state(
        call.from_user.id,
        warehouse=warehouse,
        branch=branch,
        product_type=product_type_name,
        product_name=product_name,
        action= action,
    )
    _show_list_product_details(
        call.message.chat.id,
        warehouse,
        branch,
        product_type_name,
        product_name,
        call.message.message_id,
    )
    bot.answer_callback_query(call.id)

# ==================== REQUEST HANDLERS ====================

@bot.message_handler(content_types=["contact"])
def handle_contact_request(message):
    """Ro'yxatdan o'tish uchun telefon kontaktini qabul qilish."""
    user_id = message.from_user.id
    contact = message.contact
    if contact and contact.user_id and contact.user_id != user_id:
        bot.send_message(message.chat.id, "Iltimos, o'zingizning telefon raqamingizni yuboring.")
        return

    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name or (contact.first_name if contact else "Foydalanuvchi")
    last_name = message.from_user.last_name or (contact.last_name if contact else None)
    phone = contact.phone_number if contact else None
    display_name = _display_actor_name(username, first_name)

    db = get_db()
    if not db.get_user(user_id):
        db.add_user(user_id, username, first_name, approved=False)
    db.update_user_contact(user_id, phone=phone, first_name=first_name, last_name=last_name)
    db.add_request(user_id, display_name)

    bot.send_message(
        message.chat.id,
        "So'rov yuborildi. Admin tasdiqlagandan keyin login ma'lumotlari bot orqali keladi.",
        reply_markup=telebot.types.ReplyKeyboardRemove(),
    )

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("Tasdiqlash", callback_data=f"approve_user:{user_id}"),
        telebot.types.InlineKeyboardButton("Rad qilish", callback_data=f"reject_user:{user_id}"),
    )
    bot.send_message(
        ADMIN_ID,
        f"Yangi so'rov:\n\nFoydalanuvchi: {display_name}\nUser ID: {user_id}\nTelefon: {phone or '-'}",
        reply_markup=markup,
    )

@bot.callback_query_handler(func=lambda call: call.data == "send_request")
def handle_send_request(call):
    """So'rov yuborish"""
    user_id = call.from_user.id
    username = call.from_user.username or "NoUsername"
    display_name = _display_actor_name(username, call.from_user.first_name)
    user_states.pop(user_id, None)
    
    db = get_db()
    db.add_request(user_id, display_name)
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        MESSAGES["request_sent"],
        call.message.chat.id,
        call.message.message_id
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve_user:{user_id}"),
        telebot.types.InlineKeyboardButton("❌ Rad Qilish", callback_data=f"reject_user:{user_id}")
    )
    
    bot.send_message(
        ADMIN_ID,
        f"📩 Yangi so'rov:\n\n👤 Foydalanuvchi: {display_name}\n🆔 User ID: {user_id}",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_user:"))
def handle_approve_user(call):
    """Admin tasdiqlagandan keyin foydalanuvchi toifasini so'rash."""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    
    user_id = int(call.data.split(":")[1])
    bot.answer_callback_query(call.id, "Toifani tanlang")
    bot.edit_message_text(
        f"✅ Tasdiqlash: <code>{user_id}</code>\n\nQaysi toifaga kiritasiz?",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_request_role_menu(user_id),
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_user_role:"))
def handle_approve_user_role(call):
    """Tanlangan toifa bo'yicha foydalanuvchini tasdiqlash va link yuborish."""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return

    _, user_id_text, role = call.data.split(":", 2)
    if role not in {"employee", "customer"}:
        bot.answer_callback_query(call.id, "Noto'g'ri toifa", show_alert=True)
        return

    user_id = int(user_id_text)
    password = secrets.token_urlsafe(6)
    
    db = get_db()
    db.approve_user(user_id, role=role, password_hash=generate_password_hash(password))
    db.delete_request(user_id)
    approved_user = db.get_user(user_id)
    if approved_user and role == "customer":
        db.upsert_customer(
            _display_actor_name(approved_user.get("username"), approved_user.get("first_name")),
            phone=approved_user.get("phone"),
            user_id=user_id,
            telegram=approved_user.get("username"),
            source="telegram",
        )
    if approved_user and role == "employee":
        db.upsert_employee(
            approved_user.get("first_name") or "Xodim",
            approved_user.get("last_name"),
            phone=approved_user.get("phone"),
            user_id=user_id,
            position="Xodim",
        )
    
    role_label = "xodim" if role == "employee" else "mijoz"
    bot.answer_callback_query(call.id, "✅ Tasdiqlandi")
    bot.edit_message_text(
        f"✅ Foydalanuvchi <code>{user_id}</code> tasdiqlandi.\n👤 Toifa: <b>{role_label}</b>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML",
    )
    
    login = str(user_id)
    user = db.get_user(user_id)
    if user and user.get("username") and user.get("username") != "NoUsername":
        login = user["username"]
    bot.send_message(user_id, make_login_message(role, login, password), reply_markup=_app_only_menu(role), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_user:"))
def handle_reject_user(call):
    """Foydalanuvchini rad qilish"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, MESSAGES["error_access_denied"], show_alert=True)
        return
    
    user_id = int(call.data.split(":")[1])
    db = get_db()
    db.reject_user(user_id)
    db.delete_request(user_id)
    
    bot.answer_callback_query(call.id, "❌ Rad qilindi")
    bot.edit_message_text(
        f"❌ Foydalanuvchi {user_id} rad qilindi",
        call.message.chat.id,
        call.message.message_id
    )
    
    bot.send_message(user_id, MESSAGES["user_rejected"])

# ==================== MISC HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data == "close_menu")
def handle_close_menu(call):
    """Menyu yopish"""
    user_id = call.from_user.id
    user_states.pop(user_id, None)
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "user_main")
def handle_user_main(call):
    """Eski callback uchun foydalanuvchi asosiy menyusi"""
    user_id = call.from_user.id
    warehouse = _user_state(user_id).get("warehouse")
    user_states.pop(user_id, None)
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    if warehouse:
        bot.send_message(call.message.chat.id, "👋 Asosiy Menyu", reply_markup=user_main_menu(warehouse))
    else:
        bot.send_message(call.message.chat.id, "🏭 Skladni tanlang:", reply_markup=user_warehouse_menu())

# ==================== WEBHOOK ====================

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    """Webhook endpoint"""
    try:
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        logger.info("✅ Webhook received")
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
    return "ok", 200

# Line 2660 dan oldin qo'shish:
# ==================== MODULE REGISTRATION ====================
logger.info("🔌 Modullar ro'yxatlanmoqda...")
try:
    register_group_handlers(bot, user_states, ADMIN_ID)
    register_admin_users_handlers(bot, user_states, ADMIN_ID)
    logger.info("✅ Barcha modullar ro'yxatlandi")
except Exception as e:
    logger.error(f"❌ Modul ro'yxatlash xatosi: {e}")

@app.route('/')
def index():
    """Web panel bosh sahifasiga yo'naltirish."""
    return redirect("/dashboard")

register_web_routes(app)

def _configure_telegram_webhook():
    """Render/Gunicorn ishga tushganda Telegram webhookni deploy URLga bog'laydi."""
    if not BOT_TOKEN or not WEB_APP_URL:
        logger.info("ℹ️ BOT_TOKEN yoki WEB_APP_URL yo'q, Telegram webhook avtomatik sozlanmadi")
        return

    webhook_url = f"{WEB_APP_URL}/{BOT_TOKEN}"
    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        logger.info("✅ Telegram webhook sozlandi: %s", webhook_url)
    except Exception as e:
        logger.error("❌ Telegram webhook sozlash xatosi: %s", e)


_configure_telegram_webhook()

# ==================== MAIN ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🤖 Bot ishga tushdi! Webhook path: /{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=port, debug=False)
