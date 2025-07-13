#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PantelMed Telegram Bot - Простий і надійний
Відправляє користувачів на веб-платформу
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# Конфігурація (з змінних середовища)
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8116552220:AAHiOZdROOQKtj09ZDvLRYZw2FNKPQrmMV4')
WEB_APP_URL = os.getenv('PLATFORM_URL', 'https://pantelmed-api.onrender.com')
ADMIN_ID = os.getenv('ADMIN_TELEGRAM_ID')

# Логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка команди /start"""
    user = update.effective_user
    
    logger.info(f"👋 User {user.id} ({user.username}) started the bot")
    
    # Вітальне повідомлення
    welcome_text = f"""
🏥 <b>Вітаємо в PantelMed, {user.first_name}!</b>

Платформа для персоналізованих медичних рекомендацій та преміум БАДів.

<b>🎯 Що ви отримаєте:</b>
💊 Персональні медичні рекомендації
🧪 Розширені списки аналізів  
🛒 Магазин сертифікованих БАДів
🚚 Доставка по всій Україні

<b>Оберіть що вас цікавить:</b>
    """
    
    # Створюємо клавіатуру з кнопками переходу
    keyboard = [
        [
            InlineKeyboardButton(
                "💊 Медична підписка", 
                url=f"{WEB_APP_URL}?source=telegram&user_id={user.id}&section=subscription"
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 Магазин БАДів", 
                url=f"{WEB_APP_URL}/shop.html?source=telegram&user_id={user.id}"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Про платформу", 
                url=f"{WEB_APP_URL}?source=telegram&user_id={user.id}&section=about"
            )
        ],
        [
            InlineKeyboardButton(
                "📞 Підтримка", 
                url="https://t.me/pantelmed_support"
            )
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка команди /help"""
    help_text = """
🤖 <b>PantelMed Bot - Довідка</b>

<b>📋 Доступні команди:</b>
/start - Головне меню
/help - Ця довідка
/shop - Магазин БАДів
/status - Статус підписки
/support - Підтримка

<b>🔗 Швидкі посилання:</b>
- Медична підписка - персональні рекомендації
- Магазин БАДів - якісні добавки  
- Підтримка - допомога та консультації

<b>💡 Як користуватися:</b>
Натискайте кнопки для переходу на платформу, 
де ви зможете оформити підписку або замовити БАДи.
    """
    
    keyboard = [
        [
            InlineKeyboardButton("🏠 Головне меню", callback_data="start_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        help_text, 
        parse_mode='HTML',
        reply_markup=reply_markup
    )

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для переходу до магазину"""
    user = update.effective_user
    
    shop_text = f"""
🛒 <b>Магазин преміум БАДів</b>

Привіт, {user.first_name}! 

<b>🌟 Наші товари:</b>
🐟 Омега-3 Преміум - $2.60
☀️ Вітамін D3 + K2 - $2.60
⚡ Магній Хелат - $2.60
🛡️ Цинк Піколінат - $2.60
💊 Мультивітамінний комплекс - $2.60
🦠 Пробіотики Преміум - $2.60

<b>✅ Переваги:</b>
- Сертифіковані виробники
- Лабораторний контроль якості
- Доставка Новою Поштою
- Оплата при отриманні
    """
    
    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 Відкрити магазин", 
                url=f"{WEB_APP_URL}/shop.html?source=telegram&user_id={user.id}"
            )
        ],
        [
            InlineKeyboardButton(
                "💊 Медична підписка", 
                url=f"{WEB_APP_URL}?source=telegram&user_id={user.id}"
            )
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        shop_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевірка статусу підписки"""
    user = update.effective_user
    
    keyboard = [
        [
            InlineKeyboardButton(
                "🔍 Перевірити статус", 
                url=f"{WEB_APP_URL}?source=telegram&user_id={user.id}&action=status"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 Оформити підписку", 
                url=f"{WEB_APP_URL}?source=telegram&user_id={user.id}"
            )
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔍 <b>Статус підписки</b>\n\nПерейдіть на платформу для перевірки вашого статусу:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

def main():
    """Запуск бота"""
    # Створюємо додаток
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Додаємо обробники команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # Запускаємо бота
    logger.info("🚀 Starting PantelMed Telegram Bot...")
    logger.info(f"🌐 Platform URL: {WEB_APP_URL}")
    
    # Для Render потрібен polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
