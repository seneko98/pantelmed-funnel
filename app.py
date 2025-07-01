from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError
import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

app = Flask(__name__)
CORS(app)  # Дозволяємо CORS для фронтенду

# Конфігурація
TRON_WALLET = "TQeHa8VdwfyybxtioW4ggbnDC1rbWe8nFa"
MIN_AMOUNT = 2.6
MIN_AMOUNT_TEST = 0.5  # Для тестового режиму
SUBSCRIPTION_DAYS = 30  # Тривалість підписки

# MongoDB підключення (спрощене, без SSL конфліктів)
MONGO_URI = "mongodb+srv://Vlad:manreds7@cluster0.d0qnz.mongodb.net/pantelmed?retryWrites=true&w=majority&appName=Cluster0"

def init_mongodb():
    """Ініціалізація MongoDB (спрощена версія як у боті)"""
    try:
        print("🔗 Connecting to MongoDB (working version)...")
        
        # Спрощене підключення БЕЗ SSL конфліктів
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=15000,
            socketTimeoutMS=20000
        )
        
        # Тестуємо підключення
        client.admin.command('ping')
        print("✅ MongoDB connection successful!")
        
        # Отримуємо базу даних
        db = client["pantelmed"]
        
        # Простий тест доступу
        try:
            collections = db.list_collection_names()
            print(f"✅ Database access successful! Collections: {collections}")
        except Exception as e:
            print(f"⚠️ Collection list failed but connection works: {e}")
        
        return client, db
        
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        return None, None

# Ініціалізація MongoDB
print("🚀 Initializing MongoDB connection...")
mongo_client, db = init_mongodb()

if mongo_client is None or db is None:
    print("🚨 CRITICAL: MongoDB connection failed! Check logs above.")
    print("🚨 Server will start but database operations will fail.")
    # Створюємо mock objects щоб сервер не падав
    users_collection = None
    transactions_collection = None
    subscriptions_collection = None
else:
    print("✅ MongoDB ready for use!")
    # Колекції MongoDB
    users_collection = db["users"]
    transactions_collection = db["transactions"] 
    subscriptions_collection = db["subscriptions"]

# Функція для безпечних операцій з MongoDB
def safe_db_operation(operation_name, operation_func):
    """Безпечне виконання операцій з базою даних"""
    try:
        if db is None:
            print(f"❌ {operation_name}: Database not connected")
            return None
        return operation_func()
    except Exception as e:
        print(f"❌ {operation_name} failed: {e}")
        return None

def generate_payment_id(user_id):
    """Генеруємо унікальний ID для платежу"""
    return hashlib.md5(f"{user_id}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]

# АВТОМАТИЗАЦІЯ ПЛАТЕЖІВ
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
        print("🔄 Payment monitoring started")
        
    def add_pending_payment(self, user_id: str, amount: float):
        """Додавання нового очікуючого платежу"""
        self.pending_payments[user_id] = PendingPayment(
            user_id=user_id,
            created_at=datetime.utcnow(),
            amount_expected=amount
        )
        print(f"➕ Added pending payment: {user_id} - {amount} USDT")
        
    def remove_pending_payment(self, user_id: str):
        """Видалення платежу зі списку очікуючих"""
        if user_id in self.pending_payments:
            del self.pending_payments[user_id]
            print(f"➖ Removed pending payment: {user_id}")
            
    def _monitor_loop(self):
        """Головний цикл моніторингу"""
        while self.running:
            try:
                self._check_all_pending_payments()
                self._cleanup_old_payments()
                time.sleep(30)  # Перевірка кожні 30 секунд
            except Exception as e:
                print(f"❌ Monitor error: {e}")
                time.sleep(60)  # При помилці чекаємо довше
                
    def _check_all_pending_payments(self):
        """Перевірка всіх очікуючих платежів"""
        if not self.pending_payments:
            return
        print(f"🔍 Checking {len(self.pending_payments)} pending payments...")
        
        for user_id, payment in list(self.pending_payments.items()):
            try:
                self._check_single_payment(payment)
            except Exception as e:
                print(f"❌ Error checking payment for {user_id}: {e}")
                
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
            print(f"❌ TRON API error for {payment.user_id}: {e}")
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
                "auto_detected": True  # Позначаємо як автоматично виявлену
            }
            
            safe_db_operation(
                "Insert auto transaction",
                lambda: transactions_collection.insert_one(transaction_data)
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
                lambda: subscriptions_collection.insert_one(subscription_data)
            )
            
            # Оновлюємо користувача
            safe_db_operation(
                "Update user auto",
                lambda: users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
                )
            )
            
            self.remove_pending_payment(user_id)
            print(f"✅ Auto-processed payment: {user_id} - {amount} USDT")
            
        except Exception as e:
            print(f"❌ Error processing payment for {user_id}: {e}")
            
    def _is_transaction_processed(self, tx_id: str) -> bool:
        """Перевірка чи транзакція вже оброблена"""
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

# Роути для статичних файлів (HTML, CSS, JS)
@app.route('/')
def serve_index():
    """Головна сторінка"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Віддаємо статичні файли (HTML, CSS)"""
    return send_from_directory('.', filename)

# Debug endpoint
@app.route("/debug-tron", methods=["GET"])
def debug_tron():
    """Debug endpoint для перевірки TRON API"""
    try:
        url = f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=5"
        headers = {"accept": "application/json"}
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Форматуємо транзакції для читабельності
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

# API endpoints
@app.route("/create-payment", methods=["POST"])
def create_payment():
    """Створюємо запит на оплату для користувача"""
    try:
        # Перевіряємо підключення до MongoDB
        if db is None:
            return jsonify({"error": "Database connection failed"}), 500
        
        data = request.get_json()
        user_id = data.get("user_id")
        test_mode = data.get("test_mode", False)
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        print(f"💳 Creating payment for user: {user_id}, test_mode: {test_mode}")
        
        # Визначаємо мінімальну суму
        min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
        
        # Створюємо унікальний payment_id для цього користувача
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
        
        # Оновлюємо або створюємо користувача з error handling
        update_result = safe_db_operation(
            "Update/create user payment",
            lambda: users_collection.update_one(
                {"user_id": user_id},
                {"$set": user_data},
                upsert=True
            )
        )
        
        if not update_result:
            return jsonify({"error": "Failed to create payment request"}), 500
        
        print(f"✅ Payment request created: {payment_id}")
        
        return jsonify({
            "payment_id": payment_id,
            "wallet_address": TRON_WALLET,
            "amount": min_amount,
            "currency": "USDT (TRC-20)",
            "test_mode": test_mode
        })
    
    except Exception as e:
        print(f"🚨 Error in create_payment: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Помилка при створенні платежу: {str(e)}"}), 500

@app.route("/check-payment", methods=["POST"])
def check_payment():
    """Перевіряємо чи надійшла оплата від користувача (браузерний ID)"""
    try:
        # Перевіряємо підключення до MongoDB
        if db is None:
            return jsonify({"error": "Database connection failed"}), 500
        
        data = request.get_json()
        user_id = data.get("user_id")
        test_mode = data.get("test_mode", False)
        auto_check = data.get("auto_check", False)  # Для автоматичних перевірок
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        if auto_check:
            print(f"🔍 Auto-checking payment for user: {user_id}, test_mode: {test_mode}")
        else:
            print(f"🔍 Manual checking payment for user: {user_id}, test_mode: {test_mode}")
        
        # Визначаємо мінімальну суму
        min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
        
        # Знаходимо користувача з error handling
        user = safe_db_operation(
            "Find user", 
            lambda: users_collection.find_one({"user_id": user_id})
        )
        
        if user is None:
            # Створюємо користувача якщо не існує
            user_data = {
                "user_id": user_id,
                "created_at": datetime.utcnow(),
                "payment_completed": False
            }
            insert_result = safe_db_operation(
                "Create user",
                lambda: users_collection.insert_one(user_data)
            )
            if insert_result:
                user = user_data
                print(f"✅ Created new user: {user_id}")
            else:
                return jsonify({"error": "Failed to create user"}), 500
        
        # Перевіряємо чи вже є активна підписка
        active_subscription = safe_db_operation(
            "Find active subscription",
            lambda: subscriptions_collection.find_one({
                "user_id": user_id,
                "expires_at": {"$gt": datetime.utcnow()},
                "active": True
            })
        )
        
        if active_subscription:
            days_left = (active_subscription["expires_at"] - datetime.utcnow()).days
            print(f"✅ Active subscription found for user {user_id}, days left: {days_left}")
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
        
        if not auto_check:
            print(f"📡 TRON API Response: {len(data_response.get('data', []))} transactions found")
        
        # Часовий діапазон для пошуку (останні 60 хвилин)
        recent_time = datetime.utcnow() - timedelta(minutes=60)
        user_created_time = user.get("created_at", recent_time)
        search_from = max(recent_time, user_created_time)
        
        if not auto_check:
            print(f"🔍 Searching transactions from: {search_from}")
            print(f"💰 Looking for amount >= {min_amount} USDT")
        
        for tx in data_response.get("data", []):
            tx_id = tx.get("transaction_id")
            value = int(tx.get("value", "0")) / (10 ** 6)
            tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            
            if not auto_check:
                print(f"🔎 Checking transaction: {value} USDT at {tx_timestamp}")
            
            # Перевірка чи транзакція вже оброблена
            existing_tx = safe_db_operation(
                "Check existing transaction",
                lambda: transactions_collection.find_one({"tx_id": tx_id})
            )
            
            # Перевіряємо умови транзакції
            if (value >= min_amount and 
                tx_timestamp > search_from and
                not existing_tx):
                
                print(f"✅ Found matching transaction: {value} USDT, tx_id: {tx_id}")
                
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
                
                tx_insert = safe_db_operation(
                    "Insert transaction",
                    lambda: transactions_collection.insert_one(transaction_data)
                )
                
                if not tx_insert:
                    return jsonify({"error": "Failed to record transaction"}), 500
                
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
                
                sub_insert = safe_db_operation(
                    "Insert subscription",
                    lambda: subscriptions_collection.insert_one(subscription_data)
                )
                
                if not sub_insert:
                    return jsonify({"error": "Failed to create subscription"}), 500
                
                # Оновлюємо статус користувача
                user_update = safe_db_operation(
                    "Update user",
                    lambda: users_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
                    )
                )
                
                print(f"✅ Subscription created for user {user_id}")
                
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
        
        if not auto_check:
            print(f"❌ No matching transactions found (need >= {min_amount} USDT)")
        
        return jsonify({
            "access": "denied", 
            "message": f"Платіж не знайдений. Надішліть {min_amount} USDT і спробуйте через кілька хвилин."
        })
        
    except requests.RequestException as e:
        print(f"🚨 TRON API error: {str(e)}")
        return jsonify({"error": f"Помилка з'єднання з TRON API: {str(e)}"}), 500
    except Exception as e:
        print(f"🚨 General error in check_payment: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Помилка при перевірці платежу: {str(e)}"}), 500

@app.route("/subscription-status", methods=["POST"])
def subscription_status():
    """Перевіряємо статус підписки користувача"""
    try:
        # Перевіряємо підключення до MongoDB
        if db is None:
            return jsonify({"error": "Database connection failed"}), 500
        
        data = request.get_json()
        user_id = data.get("user_id")
        
        if not user_id:
            return jsonify({"error": "user_id обов'язковий"}), 400
        
        print(f"🔍 Checking subscription status for user: {user_id}")
        
        # Шукаємо активну підписку з error handling
        subscription = safe_db_operation(
            "Find subscription",
            lambda: subscriptions_collection.find_one({
                "user_id": user_id,
                "expires_at": {"$gt": datetime.utcnow()},
                "active": True
            })
        )
        
        if subscription:
            days_left = (subscription["expires_at"] - datetime.utcnow()).days
            print(f"✅ Active subscription found, days left: {days_left}")
            return jsonify({
                "has_subscription": True,
                "expires_at": subscription["expires_at"].isoformat(),
                "days_left": days_left,
                "active": True
            })
        else:
            print(f"❌ No active subscription found for user {user_id}")
            return jsonify({
                "has_subscription": False,
                "active": False
            })
    
    except Exception as e:
        print(f"🚨 Error in subscription_status: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Помилка при перевірці статусу підписки: {str(e)}"}), 500

# НОВІ API ENDPOINTS ДЛЯ АВТОМАТИЗАЦІЇ
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
            
        # Зберігаємо в БД що користувач почав процес
        user_data = {
            "user_id": user_id,
            "tracking_started": datetime.utcnow(),
            "amount_expected": amount,
            "test_mode": test_mode,
            "auto_tracking": True
        }
        
        safe_db_operation(
            "Start tracking",
            lambda: users_collection.update_one(
                {"user_id": user_id},
                {"$set": user_data},
                upsert=True
            )
        )
        
        return jsonify({
            "status": "tracking_started",
            "user_id": user_id,
            "amount": amount,
            "message": "Автоматичне відстеження розпочато"
        })
        
    except Exception as e:
        print(f"❌ Error starting tracking: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/stop-payment-tracking", methods=["POST"])
def stop_payment_tracking():
    """Зупинка відстеження платежу"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        
        if payment_monitor:
            payment_monitor.remove_pending_payment(user_id)
            
        return jsonify({"status": "tracking_stopped"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/payment-tracking-status", methods=["POST"])
def payment_tracking_status():
    """Статус відстеження платежу"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        
        # Перевіряємо чи є в активному відстеженні
        is_tracking = (payment_monitor and 
                      user_id in payment_monitor.pending_payments)
        
        tracking_info = {}
        if is_tracking:
            payment = payment_monitor.pending_payments[user_id]
            tracking_info = {
                "check_count": payment.check_count,
                "last_check": payment.last_check.isoformat() if payment.last_check else None,
                "created_at": payment.created_at.isoformat(),
                "amount_expected": payment.amount_expected
            }
            
        return jsonify({
            "is_tracking": is_tracking,
            "tracking_info": tracking_info
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    """Перевірка здоров'я сервера з діагностикою MongoDB"""
    mongodb_status = "connected" if db is not None else "disconnected"
    
    # Тестуємо MongoDB якщо підключена
    mongodb_test = False
    if db is not None:
        try:
            # Простий тест - отримання інформації про колекції
            collections = db.list_collection_names()
            mongodb_test = True
        except Exception as e:
            print(f"MongoDB health check failed: {e}")
            mongodb_test = False
    
    # Інформація про автоматизацію
    monitoring_info = {
        "active": payment_monitor is not None and payment_monitor.running if payment_monitor else False,
        "pending_payments": len(payment_monitor.pending_payments) if payment_monitor else 0
    }
    
    return jsonify({
        "status": "ok", 
        "version": "PANTELMED_PAYMENT_SYSTEM_2024_AUTOMATED",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": ["/health", "/subscription-status", "/check-payment", "/create-payment", "/debug-tron", "/start-payment-tracking"],
        "mongodb": {
            "status": mongodb_status,
            "connection_test": mongodb_test,
            "uri": MONGO_URI.replace("manreds7", "***") if MONGO_URI else "not set"
        },
        "tron_wallet": TRON_WALLET,
        "automation": monitoring_info
    })

# Ініціалізація автоматизації при запуску
if db is not None:
    init_payment_monitor()

if __name__ == "__main__":
    print("🚀 Starting PantelMed Flask server with automation...")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"📂 Files in directory: {os.listdir('.')}")
    
    port = int(os.environ.get("PORT", 10000))
    print(f"📡 Server will run on port: {port}")
    print(f"🌐 Host: 0.0.0.0")
    print(f"💾 MongoDB URI configured: {'Yes' if MONGO_URI else 'No'}")
    print(f"🔗 TRON Wallet: {TRON_WALLET}")
    print(f"🤖 Automation: {'Enabled' if payment_monitor else 'Disabled'}")
    
    try:
        print("⚡ Starting Flask application...")
        app.run(host="0.0.0.0", port=port, debug=False)
        print("✅ Server started successfully!")
    except Exception as e:
        print(f"❌ Server failed to start: {e}")
        import traceback
        traceback.print_exc()
        raise
