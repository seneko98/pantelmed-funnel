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
MIN_AMOUNT = 0.5
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

# API endpoints
@app.route("/create-payment", methods=["POST"])
def create_payment():
    """Створюємо запит на оплату для користувача"""
    data = request.get_json()
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id обов'язковий"}), 400
    
    # Створюємо унікальний payment_id для цього користувача
    payment_id = generate_payment_id(user_id)
    
    # Збереження інформації про користувача та очікуваний платіж
    user_data = {
        "user_id": user_id,                    # Браузерний ID (web_timestamp_hash)
        "payment_id": payment_id,              # Унікальний ID платежу
        "amount_expected": MIN_AMOUNT,         # Очікувана сума (0.5 USDT)
        "wallet_address": TRON_WALLET,         # Адреса для оплати
        "created_at": datetime.utcnow(),       # Час створення запиту
        "payment_completed": False             # Статус оплати
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
        "amount": MIN_AMOUNT,
        "currency": "USDT (TRC-20)"
    })

@app.route("/check-payment", methods=["POST"])
def check_payment():
    """Перевіряємо чи надійшла оплата від користувача (браузерний ID)"""
    data = request.get_json()
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify({"error": "user_id обов'язковий"}), 400
    
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
        response = requests.get(url, headers=headers, timeout=10)
        data_response = response.json()
        
        # Часовий діапазон для пошуку (останні 60 хвилин)
        recent_time = datetime.utcnow() - timedelta(minutes=60)
        user_created_time = user.get("created_at", recent_time)
        search_from = max(recent_time, user_created_time)
        
        for tx in data_response.get("data", []):
            tx_id = tx.get("transaction_id")
            value = int(tx.get("value", "0")) / (10 ** 6)  # Конвертуємо в USDT
            tx_timestamp = datetime.fromtimestamp(tx["block_timestamp"] / 1000)
            
            # Перевіряємо умови транзакції
            if (value >= MIN_AMOUNT and 
                tx_timestamp > search_from and
                not transactions_collection.find_one({"tx_id": tx_id})):
                
                # Записуємо транзакцію
                transaction_data = {
                    "tx_id": tx_id,
                    "user_id": user_id,
                    "amount": value,
                    "timestamp": tx_timestamp,
                    "processed": True,
                    "created_at": datetime.utcnow()
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
                    "created_at": datetime.utcnow()
                }
                subscriptions_collection.insert_one(subscription_data)
                
                # Оновлюємо статус користувача
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"payment_completed": True, "last_payment_at": datetime.utcnow()}}
                )
                
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
            "message": "Платіж не знайдений. Спробуйте через кілька хвилин."
        })
        
    except Exception as e:
        print(f"Error checking payment: {str(e)}")
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
        "version": "FUNNEL_PAYMENT_SYSTEM_2024",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": ["/health", "/subscription-status", "/check-payment", "/create-payment"]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
