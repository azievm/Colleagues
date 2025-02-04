import logging
import sqlite3
import datetime
from telegram import __version__ as TG_VER
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    LabeledPrice,
    KeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    JobQueue
)
from telegram.constants import ParseMode

if TG_VER.split(".")[0] < "20":
    raise RuntimeError(
        f"Этот пример не совместим с вашей текущей версией PTB {TG_VER}. Для просмотра версии 20.x посетите "
        f"https://docs.python-telegram-bot.org/en/v20.x/examples.html"
    )

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

PAYMASTER_TOKEN = "***"
CURRENCY = "RUB"
PRICE = 79900  # 799.00 RUB

def create_tables():
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  name TEXT, 
                  profession TEXT, 
                  skills TEXT, 
                  bio TEXT,
                  photo_id TEXT,
                  username TEXT,
                  is_premium INTEGER DEFAULT 0,
                  subscription_end TEXT,
                  social_link TEXT)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS works
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  work_title TEXT,
                  work_description TEXT)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS connections
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  from_user INTEGER,
                  to_user INTEGER,
                  status TEXT)""")

    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "name": row[1],
            "profession": row[2],
            "skills": row[3],
            "bio": row[4],
            "photo_id": row[5],
            "username": row[6],
            "is_premium": bool(row[7]),
            "subscription_end": row[8],
            "social_link": row[9]
        }
    return None

def update_user(user_id, name, profession, skills, bio, photo_id=None, username=None, social_link=None):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("SELECT is_premium, subscription_end FROM users WHERE user_id=?", (user_id,))
    existing = c.fetchone()
    is_premium = existing[0] if existing else 0
    sub_end = existing[1] if existing else None
    
    c.execute(
        """INSERT OR REPLACE INTO users 
                 (user_id, name, profession, skills, bio, photo_id, username, social_link, is_premium, subscription_end) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, name, profession, skills, bio, photo_id, username, social_link, is_premium, sub_end),
    )
    conn.commit()
    conn.close()

def get_connections(user_id):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("""
        SELECT users.user_id, users.name, users.profession, users.username 
        FROM connections
        JOIN users ON users.user_id = CASE 
            WHEN connections.from_user = ? THEN connections.to_user 
            ELSE connections.from_user 
        END
        WHERE (connections.from_user = ? OR connections.to_user = ?)
        AND connections.status = 'accepted'
    """, (user_id, user_id, user_id))
    connections = [{
        'user_id': row[0],
        'name': row[1],
        'profession': row[2],
        'username': row[3]
    } for row in c.fetchall()]
    conn.close()
    return connections

def get_user_subscription(user_id):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("SELECT is_premium, subscription_end FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row and row[0]:
        end_date = datetime.datetime.fromisoformat(row[1])
        if datetime.datetime.now() < end_date:
            return True
        update_premium_status(user_id, False)
    return False

def update_premium_status(user_id, is_premium):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    if is_premium:
        end_date = datetime.datetime.now() + datetime.timedelta(days=30)
        c.execute("UPDATE users SET is_premium=1, subscription_end=? WHERE user_id=?", 
                 (end_date.isoformat(), user_id))
    else:
        c.execute("UPDATE users SET is_premium=0, subscription_end=NULL WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_user_works(user_id):
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("SELECT work_title, work_description FROM works WHERE user_id=?", (user_id,))
    works = c.fetchall()
    conn.close()
    return [{"title": w[0], "description": w[1]} for w in works]

def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Проверка подписок")
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_premium=1")
    premium_users = [row[0] for row in c.fetchall()]
    
    for user_id in premium_users:
        if not get_user_subscription(user_id):
            logger.info(f"Подписка истекла для пользователя {user_id}")
    conn.close()

EDITING, EDIT_PHOTO, EDIT_NAME, EDIT_PROFESSION, EDIT_SKILLS, EDIT_BIO, EDIT_SOCIAL = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [KeyboardButton("👤 Мой профиль"), KeyboardButton("🔍 Поиск связей")],
        [KeyboardButton("🤝 Мои связи"), KeyboardButton("💎 Премиум")],
        [KeyboardButton("🆘 Помощь")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите действие")
    
    text = (
        f"👋 Привет, {user.first_name}!\n"
        "Добро пожаловать в профессиональную сеть Colleagues Bot!\n\n"
        "🚀 Начни с создания профиля и находи нужные связи!\n"
        "👇 Используй кнопки ниже для навигации:"
    )
    
    await update.message.reply_text(text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *Справочник команд:*\n\n"
        "👤 _Мой профиль_ - Просмотр и редактирование профиля\n"
        "🔍 _Поиск связей_ - Найти профессионалов\n"
        "🤝 _Мои связи_ - Ваша сеть контактов\n"
        "💎 _Премиум_ - Расширенные возможности\n"
        "🆘 _Помощь_ - Это справочное меню\n\n"
        "💡 *Советы:*\n"
        "- Заполняйте профиль максимально подробно\n"
        "- Обновляйте информацию раз в месяц\n"
        "- Используйте премиум для расширения возможностей\n"
        "- Связывайтесь только с релевантными специалистами"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    user = get_user(update.effective_user.id)
    
    keyboard = [
        [
            InlineKeyboardButton("📷 Фото", callback_data="edit_photo"),
            InlineKeyboardButton("👤 Имя", callback_data="edit_name")
        ],
        [
            InlineKeyboardButton("💼 Профессия", callback_data="edit_profession"),
            InlineKeyboardButton("🛠 Навыки", callback_data="edit_skills")
        ],
        [
            InlineKeyboardButton("📖 Описание", callback_data="edit_bio"),
            InlineKeyboardButton("🌐 Соцсеть", callback_data="edit_social")
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")]
    ]
    
    text = "✏️ *Редактирование профиля:*\nВыберите что хотите изменить:"
    
    if user:
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING
    else:
        await message.reply_text("📝 Давайте создадим ваш профиль. Как вас зовут?")
        return EDIT_NAME

async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data
    
    if choice == "edit_photo":
        await query.edit_message_text("📸 Отправьте новое фото профиля (или /skip)")
        return EDIT_PHOTO
    elif choice == "edit_name":
        await query.edit_message_text("👤 Введите новое имя:")
        return EDIT_NAME
    elif choice == "edit_profession":
        await query.edit_message_text("💼 Введите новую профессию:")
        return EDIT_PROFESSION
    elif choice == "edit_skills":
        await query.edit_message_text("🛠 Введите новые навыки (через запятую):")
        return EDIT_SKILLS
    elif choice == "edit_bio":
        await query.edit_message_text("📖 Введите новое описание:")
        return EDIT_BIO
    elif choice == "edit_social":
        await query.edit_message_text("🌐 Введите новую ссылку на соцсеть:")
        return EDIT_SOCIAL
    elif choice == "cancel_edit":
        await query.edit_message_text("❌ Редактирование отменено")
        return ConversationHandler.END
    else:
        await query.edit_message_text("⚠️ Неверный выбор. Попробуйте еще раз.")
        return EDITING

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    photo_file = update.message.photo[-1].file_id
    update_user(
        user_id=update.effective_user.id,
        name=user['name'],
        profession=user['profession'],
        skills=user['skills'],
        bio=user['bio'],
        photo_id=photo_file,
        social_link=user['social_link']
    )
    await update.message.reply_text("✅ Фото профиля обновлено!")
    return ConversationHandler.END

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("✅ Фото осталось без изменений")
    return ConversationHandler.END

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    new_name = update.message.text
    update_user(
        user_id=update.effective_user.id,
        name=new_name,
        profession=user['profession'],
        skills=user['skills'],
        bio=user['bio'],
        photo_id=user['photo_id'],
        social_link=user['social_link']
    )
    await update.message.reply_text("✅ Имя обновлено!")
    return ConversationHandler.END

async def handle_profession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    new_profession = update.message.text
    update_user(
        user_id=update.effective_user.id,
        name=user['name'],
        profession=new_profession,
        skills=user['skills'],
        bio=user['bio'],
        photo_id=user['photo_id'],
        social_link=user['social_link']
    )
    await update.message.reply_text("✅ Профессия обновлена!")
    return ConversationHandler.END

async def handle_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    new_skills = update.message.text
    update_user(
        user_id=update.effective_user.id,
        name=user['name'],
        profession=user['profession'],
        skills=new_skills,
        bio=user['bio'],
        photo_id=user['photo_id'],
        social_link=user['social_link']
    )
    await update.message.reply_text("✅ Навыки обновлены!")
    return ConversationHandler.END

async def handle_bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    new_bio = update.message.text
    update_user(
        user_id=update.effective_user.id,
        name=user['name'],
        profession=user['profession'],
        skills=user['skills'],
        bio=new_bio,
        photo_id=user['photo_id'],
        social_link=user['social_link']
    )
    await update.message.reply_text("✅ Описание обновлено!")
    return ConversationHandler.END

async def handle_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = get_user(update.effective_user.id)
    social_link = update.message.text
    if social_link.startswith(("http://", "https://")):
        update_user(
            user_id=update.effective_user.id,
            name=user['name'],
            profession=user['profession'],
            skills=user['skills'],
            bio=user['bio'],
            photo_id=user['photo_id'],
            social_link=social_link
        )
        await update.message.reply_text("✅ Ссылка на соцсеть обновлена!")
    else:
        await update.message.reply_text("❌ Некорректная ссылка! Попробуйте еще раз.")
        return EDIT_SOCIAL
    return ConversationHandler.END

async def skip_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("✅ Ссылка на соцсеть осталась без изменений")
    return ConversationHandler.END

async def myprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Профиль не найден. Используйте команду создания профиля")
        return
    
    premium_badge = " 💎" if user['is_premium'] else ""
    profile_text = (
        f"👤 *Имя:* {user['name']}{premium_badge}\n\n"
        f"💼 *Профессия:* {user['profession']}\n\n"
        f"🛠️ *Навыки:* {user['skills']}\n\n"
        f"📖 *О себе:* {user['bio']}"
    )
    
    if user['social_link']:
        profile_text += f"\n\n🌐 *Соцсеть:* [Ссылка]({user['social_link']})"
    
    if user['is_premium']:
        works = get_user_works(user_id)
        if works:
            profile_text += "\n\n🎨 *Примеры работ:*"
            for i, work in enumerate(works, 1):
                profile_text += f"\n{i}. *{work['title']}*: {work['description']}"

    keyboard = [[InlineKeyboardButton("🔄 Обновить профиль", callback_data="update_profile")]]
    
    try:
        if user['photo_id']:
            await update.message.reply_photo(
                photo=user['photo_id'],
                caption=profile_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                profile_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Ошибка отображения профиля: {e}")
        await update.message.reply_text("⚠️ Ошибка отображения профиля")

async def connections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    connections = get_connections(user_id)
    
    if not connections:
        await update.message.reply_text("🤷 У вас пока нет связей. Используйте поиск!")
        return
    
    keyboard = []
    for conn in connections:
        contact_button = InlineKeyboardButton(
            "📨 Написать",
            url=f"https://t.me/{conn['username']}" if conn['username'] 
            else f"tg://user?id={conn['user_id']}"
        )
        
        buttons = [
            InlineKeyboardButton(
                f"{conn['name']} - {conn['profession']}",
                callback_data=f"view_{conn['user_id']}"
            ),
            contact_button
        ]
        keyboard.append(buttons)
    
    await update.message.reply_text(
        "🤝 *Ваши связи:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['search_skipped'] = []
    await show_next_profile(update, context)

async def show_next_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    skipped = context.user_data.get('search_skipped', [])
    
    conn = sqlite3.connect("colleagues.db")
    c = conn.cursor()
    query = """
        SELECT u.user_id, u.name, u.profession, u.skills, u.bio, u.photo_id, u.is_premium 
        FROM users u
        WHERE u.user_id != ?
        AND NOT EXISTS (
            SELECT 1 FROM connections c
            WHERE (c.from_user = ? AND c.to_user = u.user_id)
            OR (c.to_user = ? AND c.from_user = u.user_id)
        )
        AND u.user_id NOT IN ({})
        ORDER BY RANDOM()
        LIMIT 1
    """.format(','.join(['?']*len(skipped))) if skipped else """
        SELECT u.user_id, u.name, u.profession, u.skills, u.bio, u.photo_id, u.is_premium 
        FROM users u
        WHERE u.user_id != ?
        AND NOT EXISTS (
            SELECT 1 FROM connections c
            WHERE (c.from_user = ? AND c.to_user = u.user_id)
            OR (c.to_user = ? AND c.from_user = u.user_id)
        )
        ORDER BY RANDOM()
        LIMIT 1
    """
    
    params = (user_id, user_id, user_id) + tuple(skipped) if skipped else (user_id, user_id, user_id)
    
    c.execute(query, params)
    row = c.fetchone()
    conn.close()
    
    if not row:
        await context.bot.send_message(
            chat_id=user_id,
            text="🌟 Больше нет профилей для показа. Попробуйте позже!"
        )
        return
    
    profile_user = {
        'user_id': row[0],
        'name': row[1],
        'profession': row[2],
        'skills': row[3],
        'bio': row[4],
        'photo_id': row[5],
        'is_premium': row[6]
    }
    
    premium_badge = " 💎" if profile_user['is_premium'] else ""
    profile_text = (
        f"👤 *Имя:* {profile_user['name']}{premium_badge}\n\n"
        f"💼 *Профессия:* {profile_user['profession']}\n\n"
        f"🛠️ *Навыки:* {profile_user['skills']}\n\n"
        f"📖 *О себе:* {profile_user['bio']}"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🤝 Связаться", callback_data=f"connect_{profile_user['user_id']}"),
            InlineKeyboardButton("➡️ Пропустить", callback_data=f"skip_{profile_user['user_id']}")
        ]
    ]
    
    try:
        if profile_user['photo_id']:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=profile_user['photo_id'],
                caption=profile_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=profile_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Ошибка показа профиля: {e}")
        await context.bot.send_message(user_id, "⚠️ Ошибка отображения профиля")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "premium_purchase":
        await send_invoice(update, context)
    elif query.data == "cancel_premium":
        await query.edit_message_text("❌ Отмена премиум подписки.")
    elif query.data == "update_profile":
        await profile(update, context)
    elif query.data.startswith("connect_"):
        if not await check_connection_limit(user_id, context):
            return
        
        target_id = int(query.data.split("_")[1])
        
        conn = sqlite3.connect("colleagues.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO connections (from_user, to_user, status) VALUES (?, ?, 'pending')",
            (user_id, target_id),
        )
        conn.commit()
        conn.close()
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Принять", callback_data=f"accept_{user_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_{user_id}"),
            ]
        ]
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📩 Новый запрос на связь от {query.from_user.full_name}!",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            await query.edit_message_text("📩 Запрос успешно отправлен!")
        except Exception as e:
            logger.error(f"Ошибка отправки запроса: {e}")
            await query.edit_message_text("⚠️ Ошибка отправки запроса.")
        
        await show_next_profile(update, context)
    
    elif query.data.startswith("skip_"):
        skipped_id = int(query.data.split("_")[1])
        context.user_data.setdefault('search_skipped', []).append(skipped_id)
        await query.message.delete()
        await show_next_profile(update, context)
    
    elif query.data.startswith("accept_"):
        from_id = int(query.data.split("_")[1])
        to_id = user_id
        
        conn = sqlite3.connect("colleagues.db")
        c = conn.cursor()
        c.execute(
            "UPDATE connections SET status='accepted' WHERE from_user=? AND to_user=?",
            (from_id, to_id),
        )
        conn.commit()
        conn.close()
        
        await query.edit_message_text("✅ Запрос принят!")
        try:
            await context.bot.send_message(
                from_id, 
                f"🎉 {query.from_user.full_name} принял(а) ваш запрос на связь!"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")
    
    elif query.data.startswith("decline_"):
        from_id = int(query.data.split("_")[1])
        to_id = user_id
        
        conn = sqlite3.connect("colleagues.db")
        c = conn.cursor()
        c.execute(
            "DELETE FROM connections WHERE from_user=? AND to_user=?", (from_id, to_id)
        )
        conn.commit()
        conn.close()
        
        await query.edit_message_text("❌ Запрос отклонен.")
        try:
            await context.bot.send_message(
                from_id, 
                f"😞 {query.from_user.full_name} отклонил(а) ваш запрос на связь."
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")

async def check_connection_limit(user_id, context):
    now = datetime.datetime.now()
    if 'last_connection_date' not in context.user_data or \
       context.user_data['last_connection_date'].date() != now.date():
        context.user_data['connection_count'] = 0
        context.user_data['last_connection_date'] = now
    
    is_premium = get_user_subscription(user_id)
    max_connections = 200 if is_premium else 3
    
    if context.user_data.get('connection_count', 0) >= max_connections:
        msg = (f"❌ Достигнут дневной лимит соединений ({max_connections}).\n"
               "💎 Премиум-пользователи имеют увеличенный лимит.")
        if not is_premium:
            msg += "\n\nИспользуйте /premium для расширения возможностей"
        await context.bot.send_message(user_id, msg)
        return False
    
    context.user_data['connection_count'] += 1
    return True

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if get_user_subscription(update.effective_user.id):
        await update.message.reply_text("✅ У вас уже есть активная премиум подписка!")
        return
    
    text = (
        "💎 *Премиум подписка*\n\n"
        "🚀 Расширенные возможности:\n"
        "✔️ До 200 соединений в день\n"
        "✔️ Приоритет в поиске\n"
        "✔️ Возможность добавлять работы\n"
        "✔️ Специальный значок в профиле\n"
        "✔️ Прямые ссылки в профиле\n\n"
        "💰 Стоимость: *799₽/месяц*\n\n"
        "👇 Нажмите кнопку ниже для оплаты:"
    )
    keyboard = [
        [InlineKeyboardButton("💳 Купить премиум", callback_data="premium_purchase")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_premium")]
    ]
    await update.message.reply_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def send_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if get_user_subscription(user.id):
            await context.bot.send_message(user.id, "❌ У вас уже есть активная подписка!")
            return
            
        await context.bot.send_invoice(
            chat_id=user.id,
            title="Премиум подписка",
            description="Премиум доступ на 1 месяц",
            payload="premium_subscription",
            provider_token=PAYMASTER_TOKEN,
            currency=CURRENCY,
            prices=[LabeledPrice("Премиум подписка", PRICE)],
            need_email=True
        )
    except Exception as e:
        logger.error(f"Ошибка платежа: {str(e)}")
        await context.bot.send_message(
            chat_id=user.id,
            text="❌ Ошибка оплаты. Попробуйте позже."
        )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    user_id = query.from_user.id
    
    try:
        if get_user_subscription(user_id):
            await query.answer(ok=False, error_message="У вас уже есть активная подписка!")
            return
            
        if query.invoice_payload != "premium_subscription":
            await query.answer(ok=False, error_message="Ошибка платежа")
            return
            
        await query.answer(ok=True)
    except Exception as e:
        logger.error(f"Ошибка предоплаты: {e}")
        await query.answer(ok=False, error_message="Ошибка обработки платежа")

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        update_premium_status(user_id, True)
        await update.message.reply_text(
            "🎉 *Премиум подписка активирована!*\n\n"
            "Теперь вам доступны:\n"
            "- Увеличенный лимит соединений\n"
            "- Приоритет в поиске\n"
            "- Возможность добавлять работы\n"
            "- Специальный значок в профиле\n\n"
            "Спасибо за поддержку!",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка активации: {e}")
        await update.message.reply_text("❌ Ошибка активации. Обратитесь в поддержку.")

async def payment_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ *Ошибка оплаты*\n\n"
        "Возможные причины:\n"
        "- Недостаточно средств на карте\n"
        "- Карта не поддерживает онлайн-платежи\n"
        "- Техническая ошибка\n\n"
        "Попробуйте повторить оплату позже или обратитесь в поддержку.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Действие отменено.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    create_tables()
    application = Application.builder().token("***").build()
    job_queue = application.job_queue

    job_queue.run_daily(check_subscriptions, time=datetime.time(hour=0, minute=0, second=0))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("profile", profile),
            CallbackQueryHandler(profile, pattern="update_profile")
        ],
        states={
            EDITING: [CallbackQueryHandler(edit_field)],
            EDIT_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                CommandHandler("skip", skip_photo)
            ],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            EDIT_PROFESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profession)],
            EDIT_SKILLS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_skills)],
            EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bio)],
            EDIT_SOCIAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_social),
                CommandHandler("skip", skip_social)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex(r'^🆘 Помощь$'), help_command))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex(r'^🔍 Поиск связей$'), search))
    application.add_handler(MessageHandler(filters.Regex(r'^👤 Мой профиль$'), myprofile))
    application.add_handler(MessageHandler(filters.Regex(r'^🤝 Мои связи$'), connections))
    application.add_handler(MessageHandler(filters.Regex(r'^💎 Премиум$'), premium))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.TEXT, payment_error))

    application.run_polling()

if __name__ == "__main__":
    main()
