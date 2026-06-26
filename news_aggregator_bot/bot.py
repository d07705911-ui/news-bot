from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, JobQueue
)
from telegram.constants import ParseMode
from config import BOT_TOKEN, RSS_SOURCES, NEWS_PER_PAGE
from parsers.rss_parser import get_all_news
from database import Database
import re
from datetime import datetime, time
import asyncio

# Инициализация БД
db = Database()

# Кэш новостей
news_cache = []

# Список пользователей для рассылки
subscribed_users = set()

# Хранилище последних отправленных новостей
last_sent_links = set()

# ID сообщений для автоудаления
messages_to_delete = {}


def get_emoji_category(category: str) -> str:
    """Возвращает эмодзи для категории."""
    emoji_map = {
        "технологии": "💻",
        "наука": "🔬", 
        "новости": "📰"
    }
    return emoji_map.get(category, "📋")


def format_news_text(news: dict, index: int = None) -> str:
    """Форматирует текст новости."""
    title = news["title"]
    if len(title) > 80:
        title = title[:77] + "..."
    
    desc = news.get("description", "")
    desc = re.sub(r'\s+', ' ', desc).strip()
    if len(desc) > 120:
        desc = desc[:117] + "..."
    
    result = f"━━━━━━━━━━━━━━━━━━━━\n\n"
    if index:
        result += f"#{index} *{title}*\n\n"
    else:
        result += f"▶ *{title}*\n\n"
    
    if desc:
        result += f"{desc}\n\n"
    
    result += f"🕐 {news['published']}\n"
    result += f"📌 {news.get('source', 'Источник')}"
    
    return result


async def delete_old_messages(context: ContextTypes.DEFAULT_TYPE):
    """Автоудаление старых сообщений бота."""
    global messages_to_delete
    
    deleted = 0
    for user_id, msg_ids in list(messages_to_delete.items()):
        for msg_id in msg_ids[:]:  # Копируем список для итерации
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                messages_to_delete[user_id].remove(msg_id)
                deleted += 1
            except:
                # Сообщение уже удалено или недоступно
                if user_id in messages_to_delete:
                    messages_to_delete[user_id].remove(msg_id)
    
    if deleted > 0:
        print(f"[*] Deleted {deleted} old messages")
    
    # Очищаем пустые записи
    messages_to_delete = {k: v for k, v in messages_to_delete.items() if v}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение."""
    user_id = update.effective_user.id
    subscribed_users.add(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📰 Все новости", callback_data="news")],
        [InlineKeyboardButton("🔥 Топ новостей", callback_data="top")],
        [InlineKeyboardButton("📂 Категории", callback_data="categories")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("⭐ Избранное", callback_data="favorites")],
        [InlineKeyboardButton("📨 Подписка", callback_data="subscribe")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    first_name = update.effective_user.first_name or "друг"
    
    text = f"""
👋 *Привет, {first_name}!*

━━━━━━━━━━━━━━━━━━━━

📰 Я — *Новостной Агрегатор*

📚 Собираю свежие новости из:
  ├ 💻 Хабр — технологии
  ├ 📰 Лента.ру — события  
  └ 🔬 N+1 — наука

━━━━━━━━━━━━━━━━━━━━

📨 *Подпишись на рассылку*
   чтобы получать новости автоматически!

👇 Выбери действие:
"""

    msg = await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Добавляем в список для автоудаления
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по боту."""
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = """
📖 *СПРАВКА ПО БОТУ*

━━━━━━━━━━━━━━━━━━━━

⚡ *Команды:*
├ /start — Главное меню
├ /news — Все новости
├ /top — Топ-5 новостей
├ /search — Поиск
├ /favorites — Избранное
├ /subscribe — Подписка
├ /unsubscribe — Отписка
└ /help — Эта справка

━━━━━━━━━━━━━━━━━━━━

📬 *Расписание рассылки:*
├ 🌅 Утро — 09:00
├ 🌙 Вечер — 18:00
└ ⚡ Новые — сразу!

━━━━━━━━━━━━━━━━━━━━

💡 Нажми *📨 Подписка* чтобы
   получать новости автоматически!
"""

    if query:
        await query.answer()
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        msg = await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        user_id = update.effective_user.id
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)


async def show_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает топ-5 новостей."""
    query = update.callback_query
    if query:
        await query.answer("⏳ Загружаю...")
    
    all_news = get_all_news(RSS_SOURCES)
    
    if not all_news:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]]
        msg = "😔 *Новости недоступны.* Попробуйте позже."
        if query:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return
    
    top_news = all_news[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    text = """
🔥 *ТОП-5 СВЕЖИХ НОВОСТЕЙ*

━━━━━━━━━━━━━━━━━━━━
"""
    
    for i, news in enumerate(top_news):
        title = news["title"]
        if len(title) > 60:
            title = title[:57] + "..."
        
        text += f"\n{medals[i]} *{title}*\n"
        text += f"   🕐 {news['published']}\n"
        text += f"   📌 {news.get('source', '')}\n"
        text += f"   👉 [Читать]({news['link']})\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "💡 *Подпишитесь на рассылку!*"
    
    keyboard = [
        [InlineKeyboardButton("📨 Подписаться", callback_data="subscribe")],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
    ]
    
    if query:
        try:
            await query.message.delete()
        except:
            pass
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        user_id = query.from_user.id
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подписка на рассылку."""
    query = update.callback_query
    user_id = query.from_user.id
    subscribed_users.add(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📰 Читать новости", callback_data="news")],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
    ]
    
    text = """
✅ *ПОДПИСКА ОФОРМЛЕНА!*

━━━━━━━━━━━━━━━━━━━━

🎉 Теперь вы будете получать:

📬 *Утренняя* — в 09:00
📬 *Вечерняя* — в 18:00  
⚡ *Экстренные* — сразу!

━━━━━━━━━━━━━━━━━━━━

📨 В рассылке: только самые
   свежие и важные новости!

❌ Отписаться: /unsubscribe
"""

    await query.answer("🎉 Подписка оформлена!", show_alert=True)
    try:
        await query.message.delete()
    except:
        pass
    msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    user_id = query.from_user.id
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отписка от рассылки."""
    user_id = update.effective_user.id
    
    if user_id in subscribed_users:
        subscribed_users.discard(user_id)
        keyboard = [[InlineKeyboardButton("📨 Подписаться", callback_data="subscribe")]]
        msg = await update.message.reply_text(
            "❌ *Отписка выполнена.*\n\n"
            "Вы больше не будете получать рассылку.\n"
            "Нажмите кнопку чтобы подписаться снова:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)
    else:
        await update.message.reply_text(
            "ℹ️ *Вы не подписаны на рассылку.*\n\n"
            "Напишите /subscribe или нажмите 📨"
        )


async def send_notification_to_user(bot, user_id: int, news_list: list, time_name: str):
    """Отправляет уведомление."""
    try:
        if user_id not in subscribed_users:
            return
        
        keyboard = [
            [InlineKeyboardButton("📰 Все новости", callback_data="news")],
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
        ]
        
        if time_name == "morning":
            header = "🌅 *Доброе утро!*\n\n📰 *Утренняя подборка*\n\n━━━━━━━━━━━━━━━━━━━━\n"
        else:
            header = "🌙 *Добрый вечер!*\n\n📰 *Вечерняя подборка*\n\n━━━━━━━━━━━━━━━━━━━━\n"
        
        body = ""
        for i, news in enumerate(news_list[:3], 1):
            title = news["title"]
            if len(title) > 55:
                title = title[:52] + "..."
            
            body += f"\n{i}. *{title}*\n"
            body += f"   🕐 {news['published']}\n"
            body += f"   👉 [Читать]({news['link']})\n"
        
        footer = "\n━━━━━━━━━━━━━━━━━━━━\n\n💡 /news — все новости"
        
        text = header + body + footer
        
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(0.5)
        
    except Exception as e:
        print(f"Error sending to {user_id}: {e}")


async def scheduled_mailing(context: ContextTypes.DEFAULT_TYPE, time_name: str):
    """Рассылка по расписанию."""
    global last_sent_links, subscribed_users
    
    all_news = get_all_news(RSS_SOURCES)
    if not all_news:
        return
    
    new_news = [n for n in all_news if n["link"] not in last_sent_links][:5]
    if not new_news:
        return
    
    for news in new_news:
        last_sent_links.add(news["link"])
    
    if len(last_sent_links) > 50:
        last_sent_links = set(list(last_sent_links)[-50:])
    
    for user_id in subscribed_users.copy():
        await send_notification_to_user(context.bot, user_id, new_news, time_name)


async def morning_digest(context: ContextTypes.DEFAULT_TYPE):
    await scheduled_mailing(context, "morning")


async def evening_digest(context: ContextTypes.DEFAULT_TYPE):
    await scheduled_mailing(context, "evening")


async def check_new_news(context: ContextTypes.DEFAULT_TYPE):
    """Проверка новых новостей."""
    global last_sent_links, subscribed_users
    
    all_news = get_all_news(RSS_SOURCES)
    if not all_news:
        return
    
    new_news = [n for n in all_news if n["link"] not in last_sent_links]
    
    if new_news:
        new_news = new_news[:2]
        
        for user_id in subscribed_users.copy():
            try:
                keyboard = [
                    [InlineKeyboardButton("📰 Читать", callback_data="news")],
                    [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
                ]
                
                if len(new_news) == 2:
                    text = (
                        "⚡ *СВЕЖИЕ НОВОСТИ!*\n\n"
                        f"📰 *{new_news[0]['title'][:65]}...*\n"
                        f"   👉 [Читать]({new_news[0]['link']})\n\n"
                        f"📰 *{new_news[1]['title'][:65]}...*\n"
                        f"   👉 [Читать]({new_news[1]['link']})\n\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "💡 Новости уже здесь!\n"
                        "📨 /news — все новости"
                    )
                else:
                    text = (
                        "⚡ *НОВАЯ НОВОСТЬ!*\n\n"
                        f"📰 *{new_news[0]['title'][:75]}*\n\n"
                        f"🕐 {new_news[0]['published']}\n"
                        f"👉 [Читать полностью]({new_news[0]['link']})\n\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "💡 Будьте в курсе!\n"
                        "📨 /news — все новости"
                    )
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"Error: {e}")
        
        for news in new_news:
            last_sent_links.add(news["link"])


def setup_scheduled_jobs(app: Application):
    """Настройка расписания."""
    job_queue = app.job_queue
    
    job_queue.run_daily(morning_digest, time=time(hour=9, minute=0), name="morning_digest")
    job_queue.run_daily(evening_digest, time=time(hour=18, minute=0), name="evening_digest")
    job_queue.run_repeating(check_new_news, interval=900, first=60, name="check_news")
    
    # Автоудаление сообщений каждые 15 минут
    job_queue.run_repeating(delete_old_messages, interval=900, first=300, name="auto_delete")
    
    print("[*] Jobs: morning (9:00), evening (18:00), check every 15min, auto-delete every 15min")


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Категории новостей."""
    keyboard = []
    for category in RSS_SOURCES.keys():
        emoji = get_emoji_category(category)
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {category.capitalize()}", 
            callback_data=f"category_{category}"
        )])
    keyboard.append([InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")])
    
    query = update.callback_query
    await query.answer()
    
    text = """
📂 *КАТЕГОРИИ НОВОСТЕЙ*

━━━━━━━━━━━━━━━━━━━━

Выберите тему:
"""
    
    try:
        await query.message.delete()
    except:
        pass
    msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    user_id = query.from_user.id
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


async def show_news(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str = None):
    """Показывает новости."""
    global news_cache
    
    query = update.callback_query
    await query.answer("⏳ Загружаю...")
    
    all_news = get_all_news(RSS_SOURCES)
    if category:
        all_news = [n for n in all_news if n.get("category") == category]
    
    if not all_news:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]]
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="😔 *Новости не найдены.*\nПопробуйте позже.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        user_id = query.from_user.id
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)
        return
    
    news_cache = all_news
    context.user_data["news_page"] = 0
    context.user_data["current_category"] = category
    
    loading_msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ *Загружаю новости...*",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["loading_msg_id"] = loading_msg.message_id
    
    await display_news_page(update, context)


async def display_news_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображение страницы новостей."""
    page = context.user_data.get("news_page", 0)
    start = page * NEWS_PER_PAGE
    end = start + NEWS_PER_PAGE
    page_news = news_cache[start:end]
    category = context.user_data.get("current_category")
    
    if not page_news:
        return
    
    emoji = get_emoji_category(category) if category else "📰"
    total_pages = (len(news_cache) + NEWS_PER_PAGE - 1) // NEWS_PER_PAGE
    
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    # Удаляем сообщение загрузки
    loading_msg_id = context.user_data.get("loading_msg_id")
    if loading_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg_id)
        except:
            pass
        context.user_data["loading_msg_id"] = None
    
    try:
        await query.message.delete()
    except:
        pass
    
    # Заголовок
    header = f"{emoji} *НОВОСТИ*"
    if category:
        header += f" • {category.capitalize()}"
    header += f" ({page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    messages_to_send = []
    
    # Проверяем картинки
    first_with_image = None
    for news in page_news:
        if news.get("image"):
            first_with_image = news
            break
    
    # Первая новость с картинкой
    if first_with_image:
        title = first_with_image["title"]
        if len(title) > 100:
            title = title[:97] + "..."
        
        caption = f"{emoji} *{title}*\n\n"
        caption += f"🕐 {first_with_image['published']}\n"
        caption += f"📌 {first_with_image.get('source', '')}\n\n"
        caption += f"👉 [Читать на сайте]({first_with_image['link']})"
        
        keyboard = [[InlineKeyboardButton("⭐ Сохранить", callback_data=f"save_{start}")]]
        
        try:
            msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=first_with_image["image"],
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            if user_id not in messages_to_delete:
                messages_to_delete[user_id] = []
            messages_to_delete[user_id].append(msg.message_id)
        except:
            messages_to_send.append(header + f"▶ *{title}*\n👉 [Читать]({first_with_image['link']})")
        
        # Остальные новости
        other_news = [n for n in page_news if n != first_with_image]
        if other_news:
            text = "━━━━━━━━━━━━━━━━━━━━\n\n"
            for news in other_news:
                title = news["title"]
                if len(title) > 70:
                    title = title[:67] + "..."
                
                idx = start + page_news.index(news)
                text += f"▶ *{title}*\n"
                text += f"🕐 {news['published']} | "
                text += f"[📖]({news['link']}) [⭐](callback:save_{idx})\n\n"
            
            messages_to_send.append(text)
    else:
        # Все новости текстом
        messages_to_send.append(header)
        for news in page_news:
            title = news["title"]
            if len(title) > 80:
                title = title[:77] + "..."
            
            desc = news.get("description", "")
            desc = re.sub(r'\s+', ' ', desc).strip()
            if len(desc) > 100:
                desc = desc[:97] + "..."
            
            idx = start + page_news.index(news)
            
            messages_to_send.append(f"━━━━━━━━━━━━━━━━━━━━\n")
            messages_to_send.append(f"▶ *{title}*\n\n")
            if desc:
                messages_to_send.append(f"{desc}\n\n")
            messages_to_send.append(f"🕐 {news['published']} • {news.get('source', 'Источник')}\n")
            messages_to_send.append(f"[📖 Читать]({news['link']}) [⭐](callback:save_{idx})\n")
    
    # Отправляем все части
    full_text = "".join(messages_to_send)
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data="prev_page"))
    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data="next_page"))
    
    keyboard = [nav_buttons]
    keyboard.extend([
        [InlineKeyboardButton("📂 Категории", callback_data="categories"),
         InlineKeyboardButton("🔥 Топ", callback_data="top")],
        [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
    ])
    
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=full_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=False
    )
    
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


async def pagination(update: Update, context: ContextTypes.DEFAULT_TYPE, direction: int):
    current_page = context.user_data.get("news_page", 0)
    context.user_data["news_page"] = current_page + direction
    await display_news_page(update, context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    handlers = {
        "news": show_news,
        "top": show_top,
        "categories": show_categories,
        "favorites": show_favorites,
        "search": ask_search,
        "help": help_command,
        "subscribe": subscribe,
        "back_to_menu": start,
    }
    
    if data in handlers:
        await handlers[data](update, context)
    elif data.startswith("category_"):
        category = data.replace("category_", "")
        await show_news(update, context, category)
    elif data == "prev_page":
        await pagination(update, context, -1)
    elif data == "next_page":
        await pagination(update, context, 1)
    elif data.startswith("save_") or data.startswith("save_top_"):
        if data.startswith("save_top_"):
            index = int(data.replace("save_top_", ""))
            all_news = get_all_news(RSS_SOURCES)
            news = all_news[index] if index < len(all_news) else None
        else:
            index = int(data.replace("save_", ""))
            news = news_cache[index] if index < len(news_cache) else None
        
        if news:
            user_id = query.from_user.id
            if db.is_favorite(user_id, news["link"]):
                db.remove_favorite(user_id, news["link"])
                await query.answer("❌ Удалено из избранного", show_alert=True)
            else:
                db.add_favorite(user_id, news)
                await query.answer("✅ Добавлено в избранное!", show_alert=True)


async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Избранное."""
    user_id = update.callback_query.from_user.id
    favorites = db.get_favorites(user_id)
    
    if not favorites:
        keyboard = [
            [InlineKeyboardButton("📰 Новости", callback_data="news")],
            [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]
        ]
        try:
            await update.callback_query.message.delete()
        except:
            pass
        msg = await context.bot.send_message(
            chat_id=update.callback_query.message.chat_id,
            text="⭐ *ИЗБРАННОЕ ПУСТО*\n\n"
                 "━━━━━━━━━━━━━━━━━━━━\n\n"
                 "Нажмите ⭐ на любой новости\n"
                 "чтобы сохранить её здесь!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)
        return
    
    text = "⭐ *ИЗБРАННОЕ*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    keyboard = []
    
    for i, fav in enumerate(favorites[:10], 1):
        title = fav["title"]
        if len(title) > 55:
            title = title[:52] + "..."
        
        text += f"{i}. *{title}*\n"
        text += f"   📅 {fav.get('saved_at', '')[:10]}\n\n"
        keyboard.append([InlineKeyboardButton(f"📖 Открыть", url=fav["link"])])
    
    text += "━━━━━━━━━━━━━━━━━━━━"
    keyboard.append([InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")])
    
    try:
        await update.callback_query.message.delete()
    except:
        pass
    msg = await context.bot.send_message(
        chat_id=update.callback_query.message.chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


async def ask_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск."""
    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="back_to_menu")]]
    
    try:
        await update.callback_query.message.delete()
    except:
        pass
    msg = await context.bot.send_message(
        chat_id=update.callback_query.message.chat_id,
        text="🔍 *ПОИСК НОВОСТЕЙ*\n\n"
             "━━━━━━━━━━━━━━━━━━━━\n\n"
             "Введите ключевое слово:\n\n"
             "💡 Например: Python, космос, AI...",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    user_id = update.callback_query.from_user.id
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)
    context.user_data["waiting_for_search"] = True


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска."""
    if not context.user_data.get("waiting_for_search"):
        return
    
    query_text = update.message.text.lower()
    all_news = get_all_news(RSS_SOURCES)
    
    results = [
        n for n in all_news 
        if query_text in n["title"].lower() or query_text in n.get("description", "").lower()
    ]
    
    context.user_data["waiting_for_search"] = False
    global news_cache
    news_cache = results
    context.user_data["news_page"] = 0
    
    user_id = update.effective_user.id
    
    if not results:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]]
        msg = await update.message.reply_text(
            f"😔 По запросу «{update.message.text}»\n"
            "ничего не найдено.\n\n"
            "💡 Попробуйте другое слово.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        if user_id not in messages_to_delete:
            messages_to_delete[user_id] = []
        messages_to_delete[user_id].append(msg.message_id)
        return
    
    page = 0
    start = page * NEWS_PER_PAGE
    end = start + NEWS_PER_PAGE
    page_news = news_cache[start:end]
    
    text = f"🔍 *РЕЗУЛЬТАТЫ*\n━━━━━━━━━━━━━━━━━━━━\n"
    text += f"По запросу: «{update.message.text}»\n\n"
    
    for i, news in enumerate(page_news, start=start + 1):
        title = news["title"]
        if len(title) > 65:
            title = title[:62] + "..."
        
        text += f"▶ *{title}*\n"
        text += f"🕐 {news['published']} | "
        text += f"[📖]({news['link']}) [⭐](callback:save_{start + i - 1})\n\n"
    
    total_pages = (len(news_cache) + NEWS_PER_PAGE - 1) // NEWS_PER_PAGE
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data="prev_page"))
    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data="next_page"))
    
    keyboard = [nav_buttons, [InlineKeyboardButton("🏠 Меню", callback_data="back_to_menu")]]
    
    msg = await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    if user_id not in messages_to_delete:
        messages_to_delete[user_id] = []
    messages_to_delete[user_id].append(msg.message_id)


def main():
    """Запуск бота."""
    print("[*] Bot starting...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", show_top))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    
    setup_scheduled_jobs(app)
    
    print("[+] Bot is ready!")
    app.run_polling()


if __name__ == "__main__":
    main()
