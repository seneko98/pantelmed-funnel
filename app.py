# PantelMed - Повна платформа з Telegram інтеграцією, платежами, БАДи магазином та CRM системою
# app.py

from flask import Flask, jsonify, request, send_from_directory, render_template_string
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional
import logging

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Дозволяємо CORS для фронтенду

# ==============================================
# КОНФІГУРАЦІЯ
# ==============================================

# TRON Wallet Configuration
TRON_WALLET = "TQeHa8VdwfyybxtioW4ggbnDC1rbWe8nFa"
MIN_AMOUNT = 2.6
MIN_AMOUNT_TEST = 0.5
SUBSCRIPTION_DAYS = 30

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = "8116552220:AAHiOZdROOQKtj09ZDvLRYZw2FNKPQrmMV4"
TELEGRAM_BOT_USERNAME = "pantelmed_bot"
ADMIN_TELEGRAM_ID = "YOUR_ADMIN_ID"  # Замінити на ваш Telegram ID

# MongoDB Configuration
MONGO_URI = "mongodb+srv://Vlad:manreds7@cluster0.d0qnz.mongodb.net/pantelmed?retryWrites=true&w=majority&appName=Cluster0"

# Shop Configuration - ОНОВЛЕНІ ЦІНИ
SHOP_PRODUCTS = {
    'omega3': {'name': 'Омега-3 Преміум', 'price': 0.9, 'emoji': '🐟'},
    'vitamin_d3': {'name': 'Вітамін D3 + K2', 'price': 0.8, 'emoji': '☀️'},
    'magnesium': {'name': 'Магній Хелат', 'price': 0.7, 'emoji': '⚡'},
    'zinc': {'name': 'Цинк Піколінат', 'price': 0.8, 'emoji': '🛡️'},
    'complex': {'name': 'Мультивітамінний комплекс', 'price': 0.9, 'emoji': '💊'},
    'probiotics': {'name': 'Пробіотики Преміум', 'price': 0.7, 'emoji': '🦠'}
}

# Admin Panel Password
ADMIN_PASSWORD = "pantelmed_admin_2024"

# ==============================================
# MONGODB ІНІЦІАЛІЗАЦІЯ
# ==============================================

def init_mongodb():
    """Ініціалізація MongoDB підключення"""
    try:
        logger.info("🔗 Connecting to MongoDB...")
        
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=15000,
            socketTimeoutMS=20000
        )
        
        # Тестуємо підключення
        client.admin.command('ping')
        logger.info("✅ MongoDB connection successful!")
        
        # Отримуємо базу даних
        db = client["pantelmed"]
        
        # Тестуємо доступ
        try:
            collections = db.list_collection_names()
            logger.info(f"✅ Database access successful! Collections: {collections}")
        except Exception as e:
            logger.warning(f"⚠️ Collection list failed but connection works: {e}")
        
        return client, db
        
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        return None, None

# Ініціалізація MongoDB
logger.info("🚀 Initializing MongoDB connection...")
mongo_client, db = init_mongodb()

if mongo_client is None or db is None:
    logger.critical("🚨 CRITICAL: MongoDB connection failed!")
    users_collection = None
    transactions_collection = None
    subscriptions_collection = None
    orders_collection = None
else:
    logger.info("✅ MongoDB ready for use!")
    # Колекції MongoDB
    users_collection = db["users"]
    transactions_collection = db["transactions"] 
    subscriptions_collection = db["subscriptions"]
    orders_collection = db["orders"]  # Колекція для замовлень БАДів

# ==============================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ==============================================

def safe_db_operation(operation_name, operation_func):
    """Безпечне виконання операцій з базою даних"""
    try:
        if db is None:
            logger.error(f"❌ {operation_name}: Database not connected")
            return None
        return operation_func()
    except Exception as e:
        logger.error(f"❌ {operation_name} failed: {e}")
        return None

def generate_payment_id(user_id):
    """Генеруємо унікальний ID для платежу"""
    return hashlib.md5(f"{user_id}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]

def generate_order_id(user_id):
    """Генеруємо унікальний ID для замовлення"""
    timestamp = int(datetime.utcnow().timestamp())
    user_suffix = user_id.split('_')[-1][:8] if '_' in user_id else user_id[:8]
    return f"ORDER_{timestamp}_{user_suffix}"

def verify_telegram_auth(auth_data):
    """Верифікація автентичності даних від Telegram Login Widget"""
    check_hash = auth_data.pop('hash', None)
    if not check_hash:
        return False
    
    # Створюємо рядок для перевірки
    data_check_arr = []
    for key, value in sorted(auth_data.items()):
        data_check_arr.append(f"{key}={value}")
    data_check_string = '\n'.join(data_check_arr)
    
    # Створюємо секретний ключ
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    
    # Генеруємо хеш
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Перевіряємо збіг
    return hmac.compare_digest(calculated_hash, check_hash)

# ==============================================
# СТАТИЧНІ ФАЙЛИ
# ==============================================

@app.route('/')
def serve_index():
    """Головна сторінка - медична платформа з квізом"""
    return send_from_directory('.', 'index.html')

@app.route('/shop.html')
def serve_shop():
    """Сторінка магазину БАДів"""
    return send_from_directory('.', 'shop.html')

@app.route('/pay.html')
def serve_pay():
    """Універсальна сторінка оплати"""
    return send_from_directory('.', 'pay.html')

@app.route('/thankyou.html')
def serve_thankyou():
    """Сторінка подяки за підписку"""
    return send_from_directory('.', 'thankyou.html')

@app.route('/thankyou_supplements.html')
def serve_thankyou_supplements():
    """Сторінка подяки за замовлення БАДів"""
    return send_from_directory('.', 'thankyou_supplements.html')

@app.route('/admin')
def serve_admin():
    """Адмін панель з CRM функціоналом"""
    admin_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>PantelMed Admin & CRM</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: #4CAF50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }
            .stat-card { background: white; padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .stat-number { font-size: 32px; font-weight: bold; color: #4CAF50; }
            .tabs { display: flex; gap: 10px; margin: 20px 0; }
            .tab { background: white; padding: 15px 25px; border-radius: 8px; cursor: pointer; border: 2px solid #ddd; }
            .tab.active { border-color: #4CAF50; background: #4CAF50; color: white; }
            .content-area { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .orders-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
            .orders-table th, .orders-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            .orders-table th { background: #f8f9fa; }
            .status-badge { padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
            .status-pending { background: #fff3cd; color: #856404; }
            .status-paid { background: #d4edda; color: #155724; }
            .status-shipped { background: #d1ecf1; color: #0c5460; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🏥 PantelMed Admin & CRM</h1>
                <p>Управління платформою та замовленнями</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number" id="users-count">0</div>
                    <div>Всього користувачів</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="orders-count">0</div>
                    <div>Замовлень БАДів</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="subscriptions-count">0</div>
                    <div>Активних підписок</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="revenue-count">$0</div>
                    <div>Загальний дохід</div>
                </div>
            </div>
            
            <div class="tabs">
                <div class="tab active" onclick="showTab('overview')">📊 Огляд</div>
                <div class="tab" onclick="showTab('orders')">📦 Замовлення БАДів</div>
                <div class="tab" onclick="showTab('subscriptions')">💊 Підписки</div>
                <div class="tab" onclick="showTab('users')">👥 Користувачі</div>
            </div>
            
            <div class="content-area">
                <!-- Огляд -->
                <div id="overview-content">
                    <h3>📈 Статистика системи</h3>
                    <p><strong>MongoDB:</strong> <span style="color: green;">Підключено</span></p>
                    <p><strong>TRON Wallet:</strong> """ + TRON_WALLET + """</p>
                    <p><strong>Telegram Bot:</strong> @""" + TELEGRAM_BOT_USERNAME + """</p>
                    <p><strong>API URL:</strong> https://pantelmed-api.onrender.com</p>
                    
                    <h4>🛒 Каталог БАДів:</h4>
                    <ul>
                        <li>🐟 Омега-3 Преміум - $0.90</li>
                        <li>☀️ Вітамін D3 + K2 - $0.80</li>
                        <li>⚡ Магній Хелат - $0.70</li>
                        <li>🛡️ Цинк Піколінат - $0.80</li>
                        <li>💊 Мультивітамінний комплекс - $0.90</li>
                        <li>🦠 Пробіотики Преміум - $0.70</li>
                    </ul>
                </div>
                
                <!-- Замовлення БАДів -->
                <div id="orders-content" style="display: none;">
                    <h3>📦 Замовлення БАДів (CRM)</h3>
                    <p style="color: #666; font-style: italic;">🚧 CRM функціонал в розробці</p>
                    
                    <table class="orders-table">
                        <thead>
                            <tr>
                                <th>ID Замовлення</th>
                                <th>Клієнт</th>
                                <th>Товари</th>
                                <th>Сума</th>
                                <th>Статус</th>
                                <th>Дата</th>
                                <th>Дії</th>
                            </tr>
                        </thead>
                        <tbody id="orders-list">
                            <tr>
                                <td colspan="7" style="text-align: center; color: #666; padding: 40px;">
                                    📋 Замовлення з'являться тут після реалізації CRM
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                
                <!-- Підписки -->
                <div id="subscriptions-content" style="display: none;">
                    <h3>💊 Підписки</h3>
                    <div id="subscriptions-list">Завантаження...</div>
                </div>
                
                <!-- Користувачі -->
                <div id="users-content" style="display: none;">
                    <h3>👥 Користувачі</h3>
                    <div id="users-list">Завантаження...</div>
                </div>
            </div>
        </div>
        
        <script>
            // Завантажуємо статистику
            fetch('/api/admin/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('users-count').textContent = data.total_users || 0;
                    document.getElementById('orders-count').textContent = data.total_orders || 0;
                    document.getElementById('subscriptions-count').textContent = data.active_subscriptions || 0;
                    document.getElementById('revenue-count').textContent = '$' + (data.total_revenue || 0).toFixed(2);
                })
                .catch(error => console.error('Error loading stats:', error));
            
            function showTab(tabName) {
                // Сховати всі контенти
                document.querySelectorAll('[id$="-content"]').forEach(el => el.style.display = 'none');
                
                // Показати обраний
                document.getElementById(tabName + '-content').style.display = 'block';
                
                // Оновити таби
                document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
                event.target.classList.add('active');
            }
        </script>
    </body>
    </html>
    """
    return admin_html

@app.route('/<path:filename>')
def serve_static(filename):
    """Статичні файли"""
    return send_from_directory('.', filename)

# ==============================================
# TELEGRAM API ENDPOINTS
# ==============================================

@app.route("/api/telegram-login", methods=["POST"])
def telegram_login():
    """Обробка авторизації через Telegram Login Widget"""
    try:
        data = request.get_json()
        telegram_user = data.get('telegram_user')
        source = data.get('source', 'widget')
        
        if not telegram_user:
            return jsonify({"error": "Telegram user data required"}), 400
        
        logger.info(f"📱 Telegram login: {telegram_user.get('id')} via {source}")
        
        # Верифікація даних (тільки для widget)
        if source == 'widget':
            if not verify_telegram_auth(telegram_user.copy()):
                logger.warning(f"❌ Invalid Telegram auth data for user {telegram_user.get('id')}")
                return jsonify({"error": "Invalid Telegram authentication"}), 401
        
        # Створити або оновити користувача в базі
        user_data = {
            "user_id": f"tg_{telegram_user['id']}",
            "telegram_id": telegram_user['id'],
            "first_name": telegram_user.get('first_name', ''),
            "last_name": telegram_user.get('last_name', ''),
            "username": telegram_user.get('username', ''),
            "photo_url": telegram_user.get('photo_url', ''),
            "auth_date": datetime.utcnow(),
            "source": source,
            "last_login": datetime.utcnow(),
            "active": True
        }
        
        # Зберегти в MongoDB
        safe_db_operation(
            "Save telegram user",
            lambda: users_collection.update_one(
                {"telegram_id": telegram_user['id']},
                {"$set": user_data},
                upsert=True
            ) if users_collection else None
        )
        
        return jsonify({
            "status": "success",
            "user_id": user_data["user_id"],
            "message": "Telegram authentication successful"
        })
        
    except Exception as e:
        logger.error(f"❌ Telegram login error: {str(e)}")
        return jsonify({"error": "Authentication failed"}), 500

@app.route("/api/telegram-user/<user_id>", methods=["GET"])
def get_telegram_user(user_id):
    """Отримати дані користувача Telegram по ID"""
    try:
        # Пошук в базі
        if users_collection:
            user = safe_db_operation(
                "Find telegram user",
                lambda: users_collection.find_one({"telegram_id": int(user_id)})
            )
            if user:
                user['_id'] = str(user['_id'])
                if 'auth_date' in user:
                    user['auth_date'] = user['auth_date'].isoformat()
                if 'last_login' in user:
                    user['last_login'] = user['last_login'].isoformat()
                return jsonify(user)
        
        return jsonify({"error": "User not found"}), 404
        
    except Exception as e:
        logger.error(f"❌ Error fetching Telegram user {user_id}: {e}")
        return jsonify({"error": "Failed to fetch user data"}), 500

# ==============================================
# SUBSCRIPTION PAYMENT API
# ==============================================

@app.route("/check-payment", methods=["POST"])
def check_payment():
    """Перевіряємо чи надійшла оплата за ПІДПИСКУ (тільки підписка)"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        test_mode = data.get("test_mode", False)
        auto_check = data.get("auto_check", False)
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        logger.info(f"🔍 Checking SUBSCRIPTION payment for user: {user_id}, test_mode: {test_mode}")
        
        # Визначаємо мінімальну суму
        min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
        
        # Знаходимо користувача
        user = safe_db_operation(
            "Find user", 
            lambda: users_collection.find_one({"user_id": user_id}) if users_collection else None
        )
        
        if user is None:
            # Створюємо користувача якщо не існує
            user_data = {
                "user_id": user_id,
                "created_at": datetime.utcnow(),
                "payment_completed": False
            }
            safe_db_operation(
                "Create user",
                lambda: users_collection.insert_one(user_data) if users_collection else None
            )
            user = user_data
        
        # Перевіряємо чи вже є активна підписка
        active_subscription = safe_db_operation(
            "Find active subscription",
            lambda: subscriptions_collection.find_one({
                "user_id": user_id,
                "expires_at": {"$gt": datetime.utcnow()},
                "active": True
            }) if subscriptions_collection else None
        )
        
        if active_subscription:
            days_left = (active_subscription["expires_at"] - datetime.utcnow()).days
            logger.info(f"✅ Active subscription found for user {user_id}, days left: {days_left}")
            return jsonify({
                "access": "granted",
                "subscription": {
                    "expires_at": active_subscription["expires_at"].isoformat(),
                    "days_left": days_left
                }
            })
        
        # Шукаємо нові транзакції в TRON blockchain
        url = f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=20"
        headers = {"accept": "application/json"}
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data_response = response.json()
        
        # Часовий діапазон для пошуку (останні 60 хвилин)
        recent_time = datetime.utcnow() - timedelta(minutes=60)
        user_created_time = user.get("created_at", recent_time)
        search_from = max(recent_time, user_created_time)
        
        for tx in data_response.get("data", []):
            tx_id = tx.get("transaction_id")
            value = int(tx.get("value", "0")) / (10 ** 6)
            tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            
            # Перевірка чи транзакція вже оброблена
            existing_tx = safe_db_operation(
                "Check existing transaction",
                lambda: transactions_collection.find_one({"tx_id": tx_id}) if transactions_collection else None
            )
            
            # Перевіряємо умови транзакції
            if (value >= min_amount and 
                tx_timestamp > search_from and
                not existing_tx):
                
                logger.info(f"✅ Found matching SUBSCRIPTION transaction: {value} USDT, tx_id: {tx_id}")
                
                # Записуємо транзакцію
                transaction_data = {
                    "tx_id": tx_id,
                    "user_id": user_id,
                    "amount": value,
                    "timestamp": tx_timestamp,
                    "processed": True,
                    "created_at": datetime.utcnow(),
                    "test_mode": test_mode,
                    "auto_detected": auto_check,
                    "type": "subscription"
                }
                
                safe_db_operation(
                    "Insert transaction",
                    lambda: transactions_collection.insert_one(transaction_data) if transactions_collection else None
                )
                
                # Створюємо підписку
                expires_at = datetime.utcnow() + timedelta(days=SUBSCRIPTION_DAYS)
                subscription_data = {
                    "user_id": user_id,
                    "tx_id": tx_id,
                    "starts_at": datetime.utcnow(),
                    "expires_at": expires_at,
                    "active": True,
                    "created_at": datetime.utcnow(),
                    "test_mode": test_mode,
                    "auto_detected": auto_check
                }
                
                safe_db_operation(
                    "Insert subscription",
                    lambda: subscriptions_collection.insert_one(subscription_data) if subscriptions_collection else None
                )
                
                # Оновлюємо статус користувача
                safe_db_operation(
                    "Update user",
                    lambda: users_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
                    ) if users_collection else None
                )
                
                logger.info(f"✅ Subscription created for user {user_id}")
                
                return jsonify({
                    "access": "granted",
                    "subscription": {
                        "expires_at": expires_at.isoformat(),
                        "days_left": SUBSCRIPTION_DAYS
                    },
                    "transaction": {
                        "amount": value,
                        "tx_id": tx_id
                    }
                })
        
        return jsonify({
            "access": "denied", 
            "message": f"Платіж не знайдений. Надішліть {min_amount} USDT і спробуйте через кілька хвилин."
        })
        
    except requests.RequestException as e:
        logger.error(f"🚨 TRON API error: {str(e)}")
        return jsonify({"error": f"Помилка з'єднання з TRON API: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"🚨 General error in check_payment: {str(e)}")
        return jsonify({"error": f"Помилка при перевірці платежу: {str(e)}"}), 500

# ==============================================
# SUPPLEMENTS PAYMENT API - НОВИЙ
# ==============================================

@app.route("/check-supplements-payment", methods=["POST"])
def check_supplements_payment():
    """Перевіряємо чи надійшла оплата за БАДи (тільки БАДи)"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        order_id = data.get("order_id")
        expected_amount = data.get("expected_amount", 0)
        
        if not user_id or not order_id:
            return jsonify({"error": "user_id та order_id обов'язкові"}), 400
        
        logger.info(f"🔍 Checking SUPPLEMENTS payment for order: {order_id}, amount: ${expected_amount}")
        
        # Знаходимо замовлення
        order = safe_db_operation(
            "Find order", 
            lambda: orders_collection.find_one({"order_id": order_id}) if orders_collection else None
        )
        
        if not order:
            return jsonify({"error": "Замовлення не знайдено"}), 404
            
        # Перевіряємо чи вже оплачено
        if order.get("payment_status") == "paid":
            logger.info(f"✅ Order {order_id} already paid")
            return jsonify({
                "access": "granted",
                "message": "Замовлення вже оплачено",
                "order": {
                    "order_id": order_id,
                    "status": "paid",
                    "paid_at": order.get("paid_at", "").isoformat() if order.get("paid_at") else ""
                }
            })
        
        # Шукаємо нові транзакції в TRON blockchain
        url = f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=20"
        headers = {"accept": "application/json"}
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data_response = response.json()
        
        # Часовий діапазон для пошуку (з моменту створення замовлення)
        order_created = order.get("created_at", datetime.utcnow())
        search_from = order_created if isinstance(order_created, datetime) else datetime.fromisoformat(order_created.replace('Z', '+00:00'))
        
        for tx in data_response.get("data", []):
            tx_id = tx.get("transaction_id")
            value = int(tx.get("value", "0")) / (10 ** 6)
            tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            
            # Перевірка чи транзакція вже оброблена
            existing_tx = safe_db_operation(
                "Check existing transaction",
                lambda: transactions_collection.find_one({"tx_id": tx_id}) if transactions_collection else None
            )
            
            # Перевіряємо умови транзакції для БАДів
            if (abs(value - expected_amount) <= 0.1 and  # Допуск ±0.1 USDT
                tx_timestamp > search_from and
                not existing_tx):
                
                logger.info(f"✅ Found matching SUPPLEMENTS transaction: {value} USDT, tx_id: {tx_id}")
                
                # Записуємо транзакцію
                transaction_data = {
                    "tx_id": tx_id,
                    "user_id": user_id,
                    "order_id": order_id,
                    "amount": value,
                    "expected_amount": expected_amount,
                    "timestamp": tx_timestamp,
                    "processed": True,
                    "created_at": datetime.utcnow(),
                    "type": "supplements"
                }
                
                safe_db_operation(
                    "Insert supplements transaction",
                    lambda: transactions_collection.insert_one(transaction_data) if transactions_collection else None
                )
                
                # Оновлюємо статус замовлення
                safe_db_operation(
                    "Update order status",
                    lambda: orders_collection.update_one(
                        {"order_id": order_id},
                        {"$set": {
                            "payment_status": "paid",
                            "paid_at": datetime.utcnow(),
                            "tx_id": tx_id,
                            "paid_amount": value,
                            "updated_at": datetime.utcnow()
                        }}
                    ) if orders_collection else None
                )
                
                logger.info(f"✅ Supplements order {order_id} marked as paid")
                
                # TODO: Відправити TG сповіщення менеджеру (заглушка)
                # send_telegram_notification_to_manager(order, transaction_data)
                
                return jsonify({
                    "access": "granted",
                    "message": "Оплата підтверджена! Замовлення оброблене.",
                    "order": {
                        "order_id": order_id,
                        "status": "paid",
                        "paid_amount": value,
                        "tx_id": tx_id
                    }
                })
        
        return jsonify({
            "access": "denied", 
            "message": f"Платіж не знайдений. Надішліть точно ${expected_amount:.2f} USDT і спробуйте через кілька хвилин."
        })
        
    except requests.RequestException as e:
        logger.error(f"🚨 TRON API error: {str(e)}")
        return jsonify({"error": f"Помилка з'єднання з TRON API: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"🚨 General error in check_supplements_payment: {str(e)}")
        return jsonify({"error": f"Помилка при перевірці платежу БАДів: {str(e)}"}), 500

@app.route("/subscription-status", methods=["POST"])
def subscription_status():
    """Перевіряємо статус підписки користувача"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        # Шукаємо активну підписку
        subscription = safe_db_operation(
            "Find subscription",
            lambda: subscriptions_collection.find_one({
                "user_id": user_id,
                "expires_at": {"$gt": datetime.utcnow()},
                "active": True
            }) if subscriptions_collection else None
        )
        
        if subscription:
            days_left = (subscription["expires_at"] - datetime.utcnow()).days
            return jsonify({
                "has_subscription": True,
                "expires_at": subscription["expires_at"].isoformat(),
                "days_left": days_left,
                "active": True
            })
        else:
            return jsonify({
                "has_subscription": False,
                "active": False
            })
    
    except Exception as e:
        logger.error(f"🚨 Error in subscription_status: {str(e)}")
        return jsonify({"error": f"Помилка при перевірці статусу підписки: {str(e)}"}), 500

# ==============================================
# SHOP / ORDERS API
# ==============================================

@app.route("/api/products", methods=["GET"])
def get_products():
    """Отримати каталог товарів з оновленими цінами"""
    try:
        return jsonify({
            "status": "success",
            "products": SHOP_PRODUCTS
        })
    except Exception as e:
        logger.error(f"❌ Get products error: {str(e)}")
        return jsonify({"error": "Failed to get products"}), 500

@app.route("/api/create-order", methods=["POST"])
def create_order():
    """Створення нового замовлення БАДів"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Order data required"}), 400
        
        # Валідація обов'язкових полів
        required_fields = ['user_id', 'items', 'total_amount', 'order_info']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Перевірка контактної інформації
        order_info = data.get('order_info', {})
        if not order_info.get('phone') or not order_info.get('city'):
            return jsonify({"error": "Phone and city are required"}), 400
        
        # Генеруємо унікальний ID замовлення
        order_id = generate_order_id(data.get('user_id'))
        
        # Підготовка даних замовлення
        order_data = {
            "order_id": order_id,
            "user_id": data.get('user_id'),
            "telegram_user": data.get('telegram_user'),
            "items": data.get('items', []),
            "total_amount": float(data.get('total_amount', 0)),
            "order_info": {
                "first_name": order_info.get('first_name'),
                "last_name": order_info.get('last_name'),
                "phone": order_info.get('phone'),
                "city": order_info.get('city'),
                "warehouse": order_info.get('warehouse'),
                "comment": order_info.get('comment', '')
            },
            "status": "pending",
            "payment_status": "pending",  # pending -> paid -> shipped -> delivered
            "payment_method": data.get('payment_method', 'usdt_crypto'),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "source": data.get('source', 'shop')
        }
        
        logger.info(f"📦 Creating supplements order {order_id} for user {data.get('user_id')}")
        
        # Зберегти в MongoDB
        result = safe_db_operation(
            "Insert supplements order",
            lambda: orders_collection.insert_one(order_data) if orders_collection else None
        )
        
        if result:
            logger.info(f"✅ Supplements order {order_id} created successfully")
            return jsonify({
                "status": "created",
                "order_id": order_id,
                "message": "Order created successfully"
            })
        else:
            logger.error(f"❌ Failed to save supplements order {order_id}")
            return jsonify({"error": "Failed to save order"}), 500
        
    except Exception as e:
        logger.error(f"❌ Create supplements order error: {str(e)}")
        return jsonify({"error": f"Failed to create order: {str(e)}"}), 500

@app.route("/api/order/<order_id>", methods=["GET"])
def get_order(order_id):
    """Отримати конкретне замовлення"""
    try:
        if not orders_collection:
            return jsonify({"error": "Database not available"}), 500
        
        order = safe_db_operation(
            "Find order",
            lambda: orders_collection.find_one({"order_id": order_id})
        )
        
        if order:
            order['_id'] = str(order['_id'])
            if 'created_at' in order:
                order['created_at'] = order['created_at'].isoformat()
            if 'updated_at' in order:
                order['updated_at'] = order['updated_at'].isoformat()
            if 'paid_at' in order and order['paid_at']:
                order['paid_at'] = order['paid_at'].isoformat()
            
            return jsonify({
                "status": "success",
                "order": order
            })
        else:
            return jsonify({"error": "Order not found"}), 404
        
    except Exception as e:
        logger.error(f"❌ Get order error: {str(e)}")
        return jsonify({"error": "Failed to get order"}), 500

# ==============================================
# ADMIN API
# ==============================================

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    """Статистика для адмін панелі"""
    try:
        # Підрахунки з бази даних
        total_users = 0
        total_orders = 0
        total_revenue = 0
        active_subscriptions = 0
        
        if db:
            # Користувачі
            total_users = safe_db_operation(
                "Count users",
                lambda: users_collection.count_documents({}) if users_collection else 0
            ) or 0
            
            # Замовлення БАДів
            total_orders = safe_db_operation(
                "Count orders",
                lambda: orders_collection.count_documents({}) if orders_collection else 0
            ) or 0
            
            # Дохід з замовлень БАДів (тільки оплачені)
            revenue_pipeline = [
                {"$match": {"payment_status": "paid"}},
                {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
            ]
            revenue_result = safe_db_operation(
                "Calculate supplements revenue",
                lambda: list(orders_collection.aggregate(revenue_pipeline)) if orders_collection else []
            )
            if revenue_result and len(revenue_result) > 0:
                total_revenue = revenue_result[0].get('total', 0)
            
            # Дохід з підписок
            subscription_revenue = safe_db_operation(
                "Count subscriptions",
                lambda: subscriptions_collection.count_documents({}) if subscriptions_collection else 0
            ) or 0
            total_revenue += subscription_revenue * MIN_AMOUNT
            
            # Активні підписки
            active_subscriptions = safe_db_operation(
                "Count active subscriptions",
                lambda: subscriptions_collection.count_documents({
                    "expires_at": {"$gt": datetime.utcnow()},
                    "active": True
                }) if subscriptions_collection else 0
            ) or 0
        
        return jsonify({
            "total_users": total_users,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "active_subscriptions": active_subscriptions
        })
        
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return jsonify({"error": "Stats calculation failed"}), 500

# ==============================================
# CRM ЗАГЛУШКИ (ДЛЯ МАЙБУТНЬОЇ РЕАЛІЗАЦІЇ)
# ==============================================

@app.route("/api/admin/orders", methods=["GET"])
def admin_get_orders():
    """CRM: Отримати всі замовлення БАДів (заглушка)"""
    try:
        # TODO: Реалізувати повний CRM функціонал
        if not orders_collection:
            return jsonify({"orders": []})
        
        orders = safe_db_operation(
            "Get all orders",
            lambda: list(orders_collection.find({}).sort("created_at", -1).limit(50))
        )
        
        if orders:
            for order in orders:
                order['_id'] = str(order['_id'])
                if 'created_at' in order:
                    order['created_at'] = order['created_at'].isoformat()
                if 'updated_at' in order:
                    order['updated_at'] = order['updated_at'].isoformat()
                if 'paid_at' in order and order['paid_at']:
                    order['paid_at'] = order['paid_at'].isoformat()
        
        return jsonify({"orders": orders or []})
        
    except Exception as e:
        logger.error(f"Admin get orders error: {e}")
        return jsonify({"error": "Failed to get orders"}), 500

@app.route("/api/admin/order/<order_id>/status", methods=["PUT"])
def admin_update_order_status(order_id):
    """CRM: Оновити статус замовлення (заглушка)"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status:
            return jsonify({"error": "Status required"}), 400
        
        # TODO: Валідація статусів: pending, paid, shipped, delivered, cancelled
        
        result = safe_db_operation(
            "Update order status",
            lambda: orders_collection.update_one(
                {"order_id": order_id},
                {"$set": {
                    "status": new_status,
                    "updated_at": datetime.utcnow()
                }}
            ) if orders_collection else None
        )
        
        if result and result.matched_count > 0:
            logger.info(f"✅ Order {order_id} status updated to {new_status}")
            return jsonify({"status": "success", "message": "Status updated"})
        else:
            return jsonify({"error": "Order not found"}), 404
            
    except Exception as e:
        logger.error(f"Admin update order status error: {e}")
        return jsonify({"error": "Failed to update status"}), 500

# def send_telegram_notification_to_manager(order, transaction):
#     """Відправити TG сповіщення менеджеру про нове оплачене замовлення (заглушка)"""
#     # TODO: Реалізувати TG сповіщення для менеджера
#     logger.info(f"📱 TG notification (stub): New paid order {order.get('order_id')}")
#     pass

# ==============================================
# UTILITY ENDPOINTS
# ==============================================

@app.route("/debug-tron", methods=["GET"])
def debug_tron():
    """Debug endpoint для перевірки TRON API"""
    try:
        url = f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=5"
        headers = {"accept": "application/json"}
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Форматуємо транзакції
        formatted_transactions = []
        recent_time = datetime.utcnow() - timedelta(minutes=60)
        
        for tx in data.get("data", []):
            amount = int(tx.get("value", "0")) / (10 ** 6)
            timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            is_recent = timestamp > recent_time
            formatted_transactions.append({
                "amount": amount,
                "timestamp": timestamp.isoformat(),
                "tx_id": tx.get("transaction_id", "")[:16] + "...",
                "is_recent": is_recent,
                "matches_subscription": amount >= MIN_AMOUNT and is_recent,
                "matches_supplements": 0.5 <= amount <= 5.0 and is_recent
            })
        
        return jsonify({
            "status": "ok",
            "wallet": TRON_WALLET,
            "transactions_count": len(formatted_transactions),
            "transactions": formatted_transactions,
            "min_amount_subscription": MIN_AMOUNT,
            "min_amount_test": MIN_AMOUNT_TEST,
            "supplements_range": "0.5-5.0 USDT",
            "search_from": recent_time.isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "wallet": TRON_WALLET
        }), 500

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    mongodb_status = "connected" if db is not None else "disconnected"
    
    # Тестуємо MongoDB
    mongodb_test = False
    if db is not None:
        try:
            db.list_collection_names()
            mongodb_test = True
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            mongodb_test = False
    
    return jsonify({
        "status": "ok", 
        "version": "PANTELMED_UNIFIED_PLATFORM_2024_v2",
        "timestamp": datetime.utcnow().isoformat(),
        "mongodb": {
            "status": mongodb_status,
            "connection_test": mongodb_test,
            "uri": MONGO_URI.replace("manreds7", "***") if MONGO_URI else "not set"
        },
        "tron_wallet": TRON_WALLET,
        "telegram_bot": TELEGRAM_BOT_USERNAME,
        "shop_products": len(SHOP_PRODUCTS),
        "api_url": "https://pantelmed-api.onrender.com",
        "new_features": [
            "Оновлені ціни БАДів (0.7-0.9 USD)",
            "Окремий endpoint для БАДів: /check-supplements-payment",
            "CRM заглушки в адмін панелі",
            "Універсальна система оплати"
        ]
    })

# ==============================================
# ІНІЦІАЛІЗАЦІЯ ТА ЗАПУСК
# ==============================================

if __name__ == "__main__":
    logger.info("🚀 Starting PantelMed Unified Platform v2...")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"📡 Server will run on port: {port}")
    logger.info(f"💾 MongoDB: {'Connected' if db else 'Disconnected'}")
    logger.info(f"🔗 TRON Wallet: {TRON_WALLET}")
    logger.info(f"🤖 Telegram Bot: @{TELEGRAM_BOT_USERNAME}")
    logger.info(f"🛒 Shop Products: {len(SHOP_PRODUCTS)} items (NEW PRICES: $0.7-0.9)")
    logger.info(f"🌐 API URL: https://pantelmed-api.onrender.com")
    logger.info("🆕 NEW: Separate supplements payment endpoint + CRM stubs")
    
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        logger.error(f"❌ Server failed to start: {e}")
        raise
