from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
import hashlib
import os

app = Flask(__name__)
CORS(app)  # Дозволяємо CORS для фронтенду

# Конфігурація
TRON_WALLET = "TQeHa8VdwfyybxtioW4ggbnDC1rbWe8nFa"
MIN_AMOUNT = 2.6
MIN_AMOUNT_TEST = 0.5  # Для тестового режиму
SUBSCRIPTION_DAYS = 30  # Тривалість підписки

# MongoDB підключення
MONGO_URI = "mongodb+srv://Vlad:manreds7@cluster0.d0qnz.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["pantelmed"]

# Колекції MongoDB
users_collection = db["users"]              # Користувачі з браузерними ID
transactions_collection = db["transactions"] # Blockchain транзакції
subscriptions_collection = db["subscriptions"] # Активні підписки

def generate_payment_id(user_id):
    """Генеруємо унікальний ID для платежу"""
    return hashlib.md5(f"{user_id}_{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]

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
    data = request.get_json()
    user_id = data.get("user_id")
    test_mode = data.get("test_mode", False)
    
    if not user_id:
        return jsonify({"error": "user_id обов'язковий"}), 400
    
    # Визначаємо мінімальну суму
    min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
    
    # Створюємо унікальний payment_id для цього користувача
    payment_id = generate_payment_id(user_id)
    
    # Збереження інформації про користувача та очікуваний платіж
    user_data = {
        "user_id": user_id,                    # Браузерний ID (web_timestamp_hash)
        "payment_id": payment_id,              # Унікальний ID платежу
        "amount_expected": min_amount,         # Очікувана сума
        "wallet_address": TRON_WALLET,         # Адреса для оплати
        "created_at": datetime.utcnow(),       # Час створення запиту
        "payment_completed": False,            # Статус оплати
        "test_mode": test_mode                 # Тестовий режим
    }
    
    # Оновлюємо або створюємо користувача
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": user_data},
        upsert=True
    )
    
    return jsonify({
        "payment_id": payment_id,
        "wallet_address": TRON_WALLET,
        "amount": min_amount,
        "currency": "USDT (TRC-20)",
        "test_mode": test_mode
    })

@app.route("/check-payment", methods=["POST"])
def check_payment():
    """Перевіряємо чи надійшла оплата від користувача (браузерний ID)"""
    data = request.get_json()
    user_id = data.get("user_id")
    test_mode = data.get("test_mode", False)  # Тестовий режим
    
    if not user_id:
        return jsonify({"error": "user_id обов'язковий"}), 400
    
    # Визначаємо мінімальну суму
    min_amount = MIN_AMOUNT_TEST if test_mode else MIN_AMOUNT
    
    # Знаходимо користувача
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        # Створюємо користувача якщо не існує
        user_data = {
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "payment_completed": False
        }
        users_collection.insert_one(user_data)
        user = user_data
    
    # Перевіряємо чи вже є активна підписка
    active_subscription = subscriptions_collection.find_one({
        "user_id": user_id,
        "expires_at": {"$gt": datetime.utcnow()},
        "active": True
    })
    
    if active_subscription:
        return jsonify({
            "access": "granted",
            "subscription": {
                "expires_at": active_subscription["expires_at"].isoformat(),
                "days_left": (active_subscription["expires_at"] - datetime.utcnow()).days
            }
        })
    
    # Шукаємо нові транзакції в TRON blockchain
    url = f"https://api.trongrid.io/v1/accounts/{TRON_WALLET}/transactions/trc20?limit=20"
    headers = {"accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Піднімає помилку для HTTP статусів 4xx/5xx
        data_response = response.json()
        
        print(f"TRON API Response: {len(data_response.get('data', []))} transactions found")
        
        # Часовий діапазон для пошуку (останні 60 хвилин)
        recent_time = datetime.utcnow() - timedelta(minutes=60)
        user_created_time = user.get("created_at", recent_time)
        search_from = max(recent_time, user_created_time)
        
        print(f"Searching transactions from: {search_from}")
        print(f"Looking for amount >= {min_amount} USDT")
        
        for tx in data_response.get("data", []):
            tx_id = tx.get("transaction_id")
            value = int(tx.get("value", "0")) / (10 ** 6)  # Конвертуємо в USDT
            tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            
            print(f"Checking transaction: {value} USDT at {tx_timestamp}")
            
            # Перевіряємо умови транзакції
            if (value >= min_amount and 
                tx_timestamp > search_from and
                not transactions_collection.find_one({"tx_id": tx_id})):
                
                print(f"✅ Found matching transaction: {value} USDT, tx_id: {tx_id}")
                
                # Записуємо транзакцію
                transaction_data = {
                    "tx_id": tx_id,
                    "user_id": user_id,
                    "amount": value,
                    "timestamp": tx_timestamp,
                    "processed": True,
                    "created_at": datetime.utcnow(),
                    "test_mode": test_mode
                }
                transactions_collection.insert_one(transaction_data)
                
                # Створюємо підписку
                expires_at = datetime.utcnow() + timedelta(days=SUBSCRIPTION_DAYS)
                subscription_data = {
                    "user_id": user_id,
                    "tx_id": tx_id,
                    "starts_at": datetime.utcnow(),
                    "expires_at": expires_at,
                    "active": True,
                    "created_at": datetime.utcnow(),
                    "test_mode": test_mode
                }
                subscriptions_collection.insert_one(subscription_data)
                
                # Оновлюємо статус користувача
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
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
        
        print(f"❌ No matching transactions found (need >= {min_amount} USDT)")
        
        return jsonify({
            "access": "denied", 
            "message": f"Платіж не знайдений. Надішліть {min_amount} USDT і спробуйте через кілька хвилин."
        })
        
    except requests.RequestException as e:
        print(f"TRON API error: {str(e)}")
        return jsonify({"error": f"Помилка з'єднання з TRON API: {str(e)}"}), 500
    except Exception as e:
        print(f"General error: {str(e)}")
        return jsonify({"error": f"Помилка при перевірці платежу: {str(e)}"}), 500

@app.route("/subscription-status", methods=["POST"])
def subscription_status():
    """Перевіряємо статус підписки користувача"""
    data = request.get_json()
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id обов'язковий"}), 400
    
    # Шукаємо активну підписку
    subscription = subscriptions_collection.find_one({
        "user_id": user_id,
        "expires_at": {"$gt": datetime.utcnow()},
        "active": True
    })
    
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

@app.route("/health", methods=["GET"])
def health():
    """Перевірка здоров'я сервера"""
    return jsonify({
        "status": "ok", 
        "version": "FUNNEL_PAYMENT_SYSTEM_2024_FIXED",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": ["/health", "/subscription-status", "/check-payment", "/create-payment", "/debug-tron"],
        "mongo_connected": True,
        "tron_wallet": TRON_WALLET
    })

if __name__ == "__main__":
    print("🚀 Starting PantelMed Flask server...")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"📂 Files in directory: {os.listdir('.')}")
    
    port = int(os.environ.get("PORT", 10000))
    print(f"📡 Server will run on port: {port}")
    print(f"🌐 Host: 0.0.0.0")
    print(f"💾 MongoDB URI configured: {'Yes' if MONGO_URI else 'No'}")
    print(f"🔗 TRON Wallet: {TRON_WALLET}")
    
    try:
        print("⚡ Starting Flask application...")
        app.run(host="0.0.0.0", port=port, debug=False)
        print("✅ Server started successfully!")
    except Exception as e:
        print(f"❌ Server failed to start: {e}")
        import traceback
        traceback.print_exc()
        raise
