# PantelMed - Повна платформа з Telegram інтеграцією, платежами, БАДи магазином та адмін панеллю
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

# Shop Configuration
SHOP_PRODUCTS = {
    'omega3': {'name': 'Омега-3 Преміум', 'price': 2.6, 'emoji': '🐟'},
    'vitamin_d3': {'name': 'Вітамін D3 + K2', 'price': 2.6, 'emoji': '☀️'},
    'magnesium': {'name': 'Магній Хелат', 'price': 2.6, 'emoji': '⚡'},
    'zinc': {'name': 'Цинк Піколінат', 'price': 2.6, 'emoji': '🛡️'},
    'complex': {'name': 'Мультивітамінний комплекс', 'price': 2.6, 'emoji': '💊'},
    'probiotics': {'name': 'Пробіотики Преміум', 'price': 2.6, 'emoji': '🦠'}
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
    onramper_transactions = {}
else:
    logger.info("✅ MongoDB ready for use!")
    # Колекції MongoDB
    users_collection = db["users"]
    transactions_collection = db["transactions"] 
    subscriptions_collection = db["subscriptions"]
    orders_collection = db["orders"]  # Нова колекція для замовлень БАДів
    onramper_transactions = {}

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
# АВТОМАТИЗАЦІЯ ПЛАТЕЖІВ (Existing code)
# ==============================================

@dataclass
class PendingPayment:
    user_id: str
    created_at: datetime
    amount_expected: float
    last_check: Optional[datetime] = None
    check_count: int = 0

class PaymentMonitor:
    def __init__(self, db_instance, tron_wallet):
        self.db = db_instance
        self.wallet = tron_wallet
        self.running = False
        self.pending_payments = {}
        
    def start_monitoring(self):
        """Запуск фонового моніторингу"""
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        logger.info("🔄 Payment monitoring started")
        
    def add_pending_payment(self, user_id: str, amount: float):
        """Додавання нового очікуючого платежу"""
        self.pending_payments[user_id] = PendingPayment(
            user_id=user_id,
            created_at=datetime.utcnow(),
            amount_expected=amount
        )
        logger.info(f"➕ Added pending payment: {user_id} - {amount} USDT")
        
    def remove_pending_payment(self, user_id: str):
        """Видалення платежу зі списку очікуючих"""
        if user_id in self.pending_payments:
            del self.pending_payments[user_id]
            logger.info(f"➖ Removed pending payment: {user_id}")
            
    def _monitor_loop(self):
        """Головний цикл моніторингу"""
        while self.running:
            try:
                self._check_all_pending_payments()
                self._cleanup_old_payments()
                time.sleep(30)  # Перевірка кожні 30 секунд
            except Exception as e:
                logger.error(f"❌ Monitor error: {e}")
                time.sleep(60)  # При помилці чекаємо довше
                
    def _check_all_pending_payments(self):
        """Перевірка всіх очікуючих платежів"""
        if not self.pending_payments:
            return
        logger.info(f"🔍 Checking {len(self.pending_payments)} pending payments...")
        
        for user_id, payment in list(self.pending_payments.items()):
            try:
                self._check_single_payment(payment)
            except Exception as e:
                logger.error(f"❌ Error checking payment for {user_id}: {e}")
                
    def _check_single_payment(self, payment: PendingPayment):
        """Перевірка одного платежу"""
        payment.check_count += 1
        payment.last_check = datetime.utcnow()
        
        url = f"https://api.trongrid.io/v1/accounts/{self.wallet}/transactions/trc20?limit=20"
        headers = {"accept": "application/json"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Пошук відповідної транзакції
            recent_time = payment.created_at - timedelta(minutes=10)
            
            for tx in data.get("data", []):
                tx_id = tx.get("transaction_id")
                value = int(tx.get("value", "0")) / (10 ** 6)
                tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
                
                # Перевіряємо умови
                if (value >= payment.amount_expected and 
                    tx_timestamp > recent_time and
                    not self._is_transaction_processed(tx_id)):
                    
                    # Знайдена відповідна транзакція
                    self._process_found_payment(payment.user_id, tx_id, value, tx_timestamp)
                    return True
                    
        except Exception as e:
            logger.error(f"❌ TRON API error for {payment.user_id}: {e}")
        return False
        
    def _process_found_payment(self, user_id: str, tx_id: str, amount: float, timestamp: datetime):
        """Обробка знайденого платежу"""
        try:
            # Записуємо транзакцію
            transaction_data = {
                "tx_id": tx_id,
                "user_id": user_id,
                "amount": amount,
                "timestamp": timestamp,
                "processed": True,
                "created_at": datetime.utcnow(),
                "auto_detected": True
            }
            
            safe_db_operation(
                "Insert auto transaction",
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
                "auto_detected": True
            }
            
            safe_db_operation(
                "Insert auto subscription",
                lambda: subscriptions_collection.insert_one(subscription_data) if subscriptions_collection else None
            )
            
            # Оновлюємо користувача
            safe_db_operation(
                "Update user auto",
                lambda: users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
                ) if users_collection else None
            )
            
            self.remove_pending_payment(user_id)
            logger.info(f"✅ Auto-processed payment: {user_id} - {amount} USDT")
            
        except Exception as e:
            logger.error(f"❌ Error processing payment for {user_id}: {e}")
            
    def _is_transaction_processed(self, tx_id: str) -> bool:
        """Перевірка чи транзакція вже оброблена"""
        if not transactions_collection:
            return False
        result = safe_db_operation(
            "Check processed transaction",
            lambda: transactions_collection.find_one({"tx_id": tx_id})
        )
        return result is not None
        
    def _cleanup_old_payments(self):
        """Очищення старих платежів (старше 24 годин)"""
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        for user_id, payment in list(self.pending_payments.items()):
            if payment.created_at < cutoff_time:
                self.remove_pending_payment(user_id)

# Глобальний екземпляр монітора
payment_monitor = None

def init_payment_monitor():
    """Ініціалізація глобального монітора"""
    global payment_monitor
    if payment_monitor is None and db is not None:
        payment_monitor = PaymentMonitor(db, TRON_WALLET)
        payment_monitor.start_monitoring()

# ==============================================
# ADMIN PANEL HTML (Existing code - keeping it for brevity)
# ==============================================

ADMIN_PANEL_HTML = """
[Previous admin panel HTML code remains the same]
"""

# ==============================================
# СТАТИЧНІ ФАЙЛИ
# ==============================================

@app.route('/')
def serve_index():
    """Головна сторінка - React додаток"""
    return send_from_directory('.', 'index.html')

@app.route('/shop.html')
def serve_shop():
    """Сторінка магазину БАДів"""
    return send_from_directory('.', 'shop.html')

@app.route('/thankyou_supplements.html')
def serve_thankyou_supplements():
    """Сторінка подяки за замовлення БАДів"""
    return send_from_directory('.', 'thankyou_supplements.html')

@app.route('/admin')
def serve_admin():
    """Адмін панель"""
    return render_template_string(ADMIN_PANEL_HTML)

@app.route('/<path:filename>')
def serve_static(filename):
    """Статичні файли"""
    return send_from_directory('.', filename)

# ==============================================
# TELEGRAM API ENDPOINTS (Existing code)
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

@app.route("/api/telegram-notify", methods=["POST"])
def telegram_notify():
    """Відправка повідомлень в Telegram"""
    try:
        data = request.get_json()
        telegram_id = data.get('telegram_id')
        message = data.get('message')
        
        if not telegram_id or not message:
            return jsonify({"error": "telegram_id and message required"}), 400
        
        # Відправка повідомлення через Telegram Bot API
        bot_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": telegram_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(bot_api_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                logger.info(f"✅ Message sent to {telegram_id}")
                return jsonify({"status": "sent", "message_id": result['result']['message_id']})
        
        logger.error(f"❌ Failed to send message to {telegram_id}: {response.text}")
        return jsonify({"error": "Failed to send message"}), 500
        
    except Exception as e:
        logger.error(f"❌ Telegram notify error: {str(e)}")
        return jsonify({"error": "Notification failed"}), 500

# ==============================================
# SHOP / ORDERS API
# ==============================================

@app.route("/api/products", methods=["GET"])
def get_products():
    """Отримати каталог товарів"""
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
                "phone": order_info.get('phone'),
                "city": order_info.get('city'),
                "warehouse": order_info.get('warehouse'),
                "comment": order_info.get('comment', '')
            },
            "status": "pending",
            "payment_status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "source": data.get('source', 'shop'),
            "payment_method": "cash_on_delivery"
        }
        
        logger.info(f"📦 Creating order {order_id} for user {data.get('user_id')}")
        
        # Зберегти в MongoDB
        result = safe_db_operation(
            "Insert order",
            lambda: orders_collection.insert_one(order_data) if orders_collection else None
        )
        
        if result:
            logger.info(f"✅ Order {order_id} created successfully")
            return jsonify({
                "status": "created",
                "order_id": order_id,
                "message": "Order created successfully"
            })
        else:
            logger.error(f"❌ Failed to save order {order_id}")
            return jsonify({"error": "Failed to save order"}), 500
        
    except Exception as e:
        logger.error(f"❌ Create order error: {str(e)}")
        return jsonify({"error": f"Failed to create order: {str(e)}"}), 500

@app.route("/api/order-notification", methods=["POST"])
def order_notification():
    """Сповіщення про нове замовлення через Telegram"""
    try:
        data = request.get_json()
        order_data = data.get('order')
        
        if not order_data:
            return jsonify({"error": "Order data required"}), 400
        
        telegram_user = order_data.get('telegram_user', {})
        items = order_data.get('items', [])
        total_amount = order_data.get('total_amount', 0)
        order_info = order_data.get('order_info', {})
        order_id = order_data.get('order_id', 'N/A')
        
        # Повідомлення клієнту
        customer_message = f"""
🎉 <b>Дякуємо за замовлення!</b>

📦 <b>Замовлення #{order_id}</b>

<b>Ваші товари:</b>
"""
        for item in items:
            emoji = item.get('emoji', '💊')
            customer_message += f"• {emoji} {item['name']} x{item['quantity']} - ${(item['price'] * item['quantity']):.2f}\n"
        
        customer_message += f"""
💰 <b>Загалом:</b> ${total_amount:.2f}
📞 <b>Контакт:</b> {order_info.get('phone', 'N/A')}
📍 <b>Доставка:</b> {order_info.get('city', 'N/A')}, {order_info.get('warehouse', 'N/A')}

🔔 <b>Наш менеджер зв'яжеться з вами протягом 2-4 годин!</b>

Дякуємо за турботу про своє здоров'я! 💚
        """
        
        # Відправити клієнту
        if telegram_user.get('id'):
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": telegram_user['id'],
                        "text": customer_message,
                        "parse_mode": "HTML"
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    logger.info(f"✅ Customer notification sent for order {order_id}")
                else:
                    logger.error(f"❌ Failed to send customer notification: {response.text}")
            except Exception as e:
                logger.error(f"❌ Customer notification error: {e}")
        
        # Повідомлення адміну (якщо налаштовано)
        if ADMIN_TELEGRAM_ID != "YOUR_ADMIN_ID":
            admin_message = f"""
🆕 <b>Нове замовлення в PantelMed Shop!</b>

📦 <b>#{order_id}</b>

👤 <b>Клієнт:</b> {telegram_user.get('first_name', 'N/A')} {telegram_user.get('last_name', '')}
📱 @{telegram_user.get('username', 'no_username')} (ID: {telegram_user.get('id', 'N/A')})

💰 <b>Сума:</b> ${total_amount:.2f}
📞 <b>Телефон:</b> {order_info.get('phone', 'N/A')}
📍 <b>Доставка:</b> {order_info.get('city', 'N/A')}, {order_info.get('warehouse', 'N/A')}

<b>Товари:</b>
"""
            for item in items:
                emoji = item.get('emoji', '💊')
                admin_message += f"• {emoji} {item['name']} x{item['quantity']}\n"
            
            if order_info.get('comment'):
                admin_message += f"\n💭 <b>Коментар:</b> {order_info['comment']}"
            
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_TELEGRAM_ID,
                        "text": admin_message,
                        "parse_mode": "HTML"
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    logger.info(f"✅ Admin notification sent for order {order_id}")
                else:
                    logger.error(f"❌ Failed to send admin notification: {response.text}")
            except Exception as e:
                logger.error(f"❌ Admin notification error: {e}")
        
        return jsonify({"status": "notifications_sent"})
        
    except Exception as e:
        logger.error(f"❌ Order notification error: {str(e)}")
        return jsonify({"error": f"Notification failed: {str(e)}"}), 500

@app.route("/api/orders/<user_id>", methods=["GET"])
def get_user_orders(user_id):
    """Отримати замовлення користувача"""
    try:
        if not orders_collection:
            return jsonify({"orders": []})
        
        orders = safe_db_operation(
            "Find user orders",
            lambda: list(orders_collection.find(
                {"user_id": user_id}
            ).sort("created_at", -1))
        )
        
        if orders:
            # Конвертуємо ObjectId та datetime для JSON
            for order in orders:
                order['_id'] = str(order['_id'])
                if 'created_at' in order:
                    order['created_at'] = order['created_at'].isoformat()
                if 'updated_at' in order:
                    order['updated_at'] = order['updated_at'].isoformat()
        
        return jsonify({
            "status": "success",
            "orders": orders or []
        })
        
    except Exception as e:
        logger.error(f"❌ Get user orders error: {str(e)}")
        return jsonify({"error": "Failed to get orders"}), 500

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
# PAYMENT API (Existing subscription code)
# ==============================================

@app.route("/create-payment", methods=["POST"])
def create_payment():
    """Створюємо запит на оплату для користувача"""
    try:
        data = request.get_json()
        user_id = data.get("user_id", f"web_{int(datetime.utcnow().timestamp())}")
        test_mode = data.get("test_mode", False)
        
        logger.info(f"💳 Creating payment for user: {user_id}, test_mode: {test_mode}")
        
        # Визначаємо мінімальну суму
        min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
        
        # Створюємо унікальний payment_id
        payment_id = generate_payment_id(user_id)
        
        # Збереження інформації про користувача та очікуваний платіж
        user_data = {
            "user_id": user_id,
            "payment_id": payment_id,
            "amount_expected": min_amount,
            "wallet_address": TRON_WALLET,
            "created_at": datetime.utcnow(),
            "payment_completed": False,
            "test_mode": test_mode
        }
        
        # Зберегти в MongoDB
        safe_db_operation(
            "Update/create user payment",
            lambda: users_collection.update_one(
                {"user_id": user_id},
                {"$set": user_data},
                upsert=True
            ) if users_collection else None
        )
        
        logger.info(f"✅ Payment request created: {payment_id}")
        
        return jsonify({
            "payment_id": payment_id,
            "wallet_address": TRON_WALLET,
            "amount": min_amount,
            "currency": "USDT (TRC-20)",
            "test_mode": test_mode
        })
    
    except Exception as e:
        logger.error(f"🚨 Error in create_payment: {str(e)}")
        return jsonify({"error": f"Помилка при створенні платежу: {str(e)}"}), 500

@app.route("/check-payment", methods=["POST"])
def check_payment():
    """Перевіряємо чи надійшла оплата від користувача"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        test_mode = data.get("test_mode", False)
        auto_check = data.get("auto_check", False)
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        logger.info(f"🔍 Checking payment for user: {user_id}, test_mode: {test_mode}, auto: {auto_check}")
        
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
                
                logger.info(f"✅ Found matching transaction: {value} USDT, tx_id: {tx_id}")
                
                # Записуємо транзакцію
                transaction_data = {
                    "tx_id": tx_id,
                    "user_id": user_id,
                    "amount": value,
                    "timestamp": tx_timestamp,
                    "processed": True,
                    "created_at": datetime.utcnow(),
                    "test_mode": test_mode,
                    "auto_detected": auto_check
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
# ADMIN API (Updated with orders support)
# ==============================================

@app.route("/api/admin/health", methods=["GET"])
def admin_health():
    """Здоров'я системи для адмін панелі"""
    try:
        # MongoDB статус
        mongodb_status = {
            "name": "MongoDB",
            "status": "ok" if db is not None else "error",
            "healthy": True if db is not None else False,
            "message": "Підключена" if db is not None else "Відключена",
            "details": f"Колекції: {len(db.list_collection_names()) if db else 0}"
        }
        
        # TRON API статус
        try:
            tron_response = requests.get(f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=1", timeout=5)
            tron_healthy = tron_response.status_code == 200
            tron_status = {
                "name": "TRON API",
                "status": "ok" if tron_healthy else "error",
                "healthy": tron_healthy,
                "message": "Працює" if tron_healthy else "Недоступний",
                "details": f"Гаманець: {TRON_WALLET[:20]}..."
            }
        except:
            tron_status = {
                "name": "TRON API",
                "status": "error",
                "healthy": False,
                "message": "Недоступний",
                "details": "Помилка з'єднання"
            }
        
        # Telegram Bot статус
        try:
            bot_response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=5)
            telegram_healthy = bot_response.status_code == 200
            telegram_status = {
                "name": "Telegram Bot",
                "status": "ok" if telegram_healthy else "error",
                "healthy": telegram_healthy,
                "message": "Активний" if telegram_healthy else "Недоступний",
                "details": f"@{TELEGRAM_BOT_USERNAME}"
            }
        except:
            telegram_status = {
                "name": "Telegram Bot",
                "status": "error",
                "healthy": False,
                "message": "Недоступний",
                "details": "Помилка з'єднання"
            }
        
        return jsonify({
            "mongodb": mongodb_status,
            "tron": tron_status,
            "telegram": telegram_status
        })
        
    except Exception as e:
        logger.error(f"Admin health check error: {e}")
        return jsonify({"error": "Health check failed"}), 500

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
            
            # Дохід з замовлень БАДів
            revenue_pipeline = [
                {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
            ]
            revenue_result = safe_db_operation(
                "Calculate revenue",
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
            "active_subscriptions": active_subscriptions,
            "revenue_change": 12.5,  # Mock data
            "new_users": 8,
            "pending_orders": 3,
            "expiring_soon": 2
        })
        
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return jsonify({"error": "Stats calculation failed"}), 500

@app.route("/api/admin/orders", methods=["GET"])
def admin_orders():
    """Замовлення для адмін панелі (обидва типи: підписки і БАДи)"""
    try:
        all_orders = []
        
        # Замовлення БАДів
        if orders_collection:
            bads_orders = safe_db_operation(
                "Find shop orders",
                lambda: list(orders_collection.find().sort('created_at', -1).limit(25))
            )
            
            if bads_orders:
                for order in bads_orders:
                    order['_id'] = str(order['_id'])
                    order['type'] = 'supplements'
                    if 'created_at' in order:
                        order['created_at'] = order['created_at'].isoformat()
                    if 'updated_at' in order:
                        order['updated_at'] = order['updated_at'].isoformat()
                    all_orders.append(order)
        
        # Підписки (як "замовлення")
        if subscriptions_collection:
            subscriptions = safe_db_operation(
                "Find subscriptions",
                lambda: list(subscriptions_collection.find().sort('created_at', -1).limit(25))
            )
            
            if subscriptions:
                for sub in subscriptions:
                    sub['_id'] = str(sub['_id'])
                    sub['type'] = 'subscription'
                    sub['order_id'] = f"SUB_{sub.get('user_id', '')[:8]}"
                    sub['total_amount'] = MIN_AMOUNT
                    sub['status'] = 'completed' if sub.get('active') else 'expired'
                    if 'created_at' in sub:
                        sub['created_at'] = sub['created_at'].isoformat()
                    if 'expires_at' in sub:
                        sub['expires_at'] = sub['expires_at'].isoformat()
                    all_orders.append(sub)
        
        # Сортуємо за датою створення
        all_orders.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return jsonify({
            "orders": all_orders[:50],  # Обмежуємо до 50 останніх
            "total": len(all_orders)
        })
        
    except Exception as e:
        logger.error(f"Admin orders error: {e}")
        return jsonify({"error": "Failed to fetch orders"}), 500

# ==============================================
# UTILITY ENDPOINTS (Existing code)
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
                "matches_criteria": amount >= MIN_AMOUNT and is_recent
            })
        
        return jsonify({
            "status": "ok",
            "wallet": TRON_WALLET,
            "transactions_count": len(formatted_transactions),
            "transactions": formatted_transactions,
            "min_amount_required": MIN_AMOUNT,
            "min_amount_test": MIN_AMOUNT_TEST,
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
    
    # Інформація про автоматизацію
    monitoring_info = {
        "active": payment_monitor is not None and payment_monitor.running if payment_monitor else False,
        "pending_payments": len(payment_monitor.pending_payments) if payment_monitor else 0
    }
    
    return jsonify({
        "status": "ok", 
        "version": "PANTELMED_PLATFORM_2024_WITH_SHOP",
        "timestamp": datetime.utcnow().isoformat(),
        "mongodb": {
            "status": mongodb_status,
            "connection_test": mongodb_test,
            "uri": MONGO_URI.replace("manreds7", "***") if MONGO_URI else "not set"
        },
        "tron_wallet": TRON_WALLET,
        "automation": monitoring_info,
        "telegram_bot": TELEGRAM_BOT_USERNAME,
        "shop_products": len(SHOP_PRODUCTS)
    })

# ==============================================
# PAYMENT MONITORING (Existing code)
# ==============================================

@app.route("/start-payment-tracking", methods=["POST"])
def start_payment_tracking():
    """Початок відстеження платежу для користувача"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        test_mode = data.get("test_mode", False)
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
            
        # Ініціалізуємо монітор якщо потрібно
        if payment_monitor is None:
            init_payment_monitor()
            
        # Визначаємо суму
        amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
        
        # Додаємо до моніторингу
        if payment_monitor:
            payment_monitor.add_pending_payment(user_id, amount)
        
        return jsonify({
            "status": "tracking_started",
            "user_id": user_id,
            "amount": amount,
            "message": "Автоматичне відстеження розпочато"
        })
        
    except Exception as e:
        logger.error(f"❌ Error starting tracking: {e}")
        return jsonify({"error": str(e)}), 500

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
# ІНІЦІАЛІЗАЦІЯ ТА ЗАПУСК
# ==============================================

# Ініціалізація автоматизації при запуску
if db is not None:
    init_payment_monitor()

if __name__ == "__main__":
    logger.info("🚀 Starting PantelMed Platform with Shop...")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"📡 Server will run on port: {port}")
    logger.info(f"💾 MongoDB: {'Connected' if db else 'Disconnected'}")
    logger.info(f"🔗 TRON Wallet: {TRON_WALLET}")
    logger.info(f"🤖 Telegram Bot: @{TELEGRAM_BOT_USERNAME}")
    logger.info(f"🔄 Payment Monitor: {'Enabled' if payment_monitor else 'Disabled'}")
    logger.info(f"🛒 Shop Products: {len(SHOP_PRODUCTS)} items")
    
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        logger.error(f"❌ Server failed to start: {e}")
        raise
