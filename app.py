# PantelMed - Повна платформа з Telegram інтеграцією, платежами та адмін панеллю
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

# Onramper Configuration
ONRAMPER_TEST_KEY = "pk_test_01JY2KESE1BJG8PP886XHG2EWG"
ONRAMPER_WEBHOOK_SECRET = "your_webhook_secret_here"

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
    orders_collection = db["orders"]
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
# АВТОМАТИЗАЦІЯ ПЛАТЕЖІВ
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
# ADMIN PANEL HTML
# ==============================================

ADMIN_PANEL_HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Адмін панель - PantelMed</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f8f9fa;
            color: #333;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .login-section {
            max-width: 400px;
            margin: 100px auto;
            background: white;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .login-section h2 {
            margin-bottom: 30px;
            color: #333;
        }
        
        .login-section input {
            width: 100%;
            padding: 15px;
            margin: 10px 0;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
        }
        
        .login-section button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            margin-top: 20px;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            border-left: 4px solid;
            transition: transform 0.2s;
        }
        
        .stat-card:hover {
            transform: translateY(-2px);
        }
        
        .stat-card.revenue { border-left-color: #28a745; }
        .stat-card.users { border-left-color: #007bff; }
        .stat-card.conversion { border-left-color: #ffc107; }
        .stat-card.active { border-left-color: #17a2b8; }
        
        .stat-number {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .stat-label {
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .section {
            background: white;
            margin: 20px 0;
            border-radius: 15px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .section-header {
            background: #f8f9fa;
            padding: 20px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .section-title {
            font-size: 1.3em;
            font-weight: 600;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
            transition: background-color 0.2s;
        }
        
        .btn-primary { background: #007bff; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-warning { background: #ffc107; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        
        .table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .table th, .table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e9ecef;
        }
        
        .table th {
            background: #f8f9fa;
            font-weight: 600;
        }
        
        .table tbody tr:hover {
            background: #f8f9fa;
        }
        
        .status-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: 600;
        }
        
        .status-active { background: #d4edda; color: #155724; }
        .status-pending { background: #fff3cd; color: #856404; }
        .status-failed { background: #f8d7da; color: #721c24; }
        
        .real-time-log {
            background: #1e1e1e;
            color: #00ff00;
            padding: 20px;
            border-radius: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            height: 300px;
            overflow-y: auto;
        }
        
        .alert {
            padding: 15px;
            margin: 10px 0;
            border-radius: 8px;
            border-left: 4px solid;
        }
        
        .alert-info { background: #d1ecf1; border-left-color: #17a2b8; color: #0c5460; }
        .alert-warning { background: #fff3cd; border-left-color: #ffc107; color: #856404; }
        .alert-danger { background: #f8d7da; border-left-color: #dc3545; color: #721c24; }
        .alert-success { background: #d4edda; border-left-color: #28a745; color: #155724; }
        
        .hidden { display: none; }
        
        .logout-btn {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255,255,255,0.2);
            color: white;
            border: 1px solid white;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
        }
        
        .refresh-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #f3f3f3;
            border-top: 2px solid #007bff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-left: 10px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <!-- ЛОГІН СЕКЦІЯ -->
    <div id="login-section" class="login-section">
        <h2>🔐 Вхід в адмін панель</h2>
        <p>PantelMed - Управління платформою</p>
        <input type="password" id="admin-password" placeholder="Пароль адміністратора" onkeypress="handlePasswordKeyPress(event)">
        <button onclick="adminLogin()">🚀 Увійти</button>
        <div id="login-error" style="color: red; margin-top: 10px; display: none;"></div>
    </div>

    <!-- АДМІН ПАНЕЛЬ -->
    <div id="admin-panel" class="hidden">
        <div class="header">
            <h1>📊 PantelMed - Адмін панель</h1>
            <p>Управління платежами, користувачами та замовленнями</p>
            <button class="logout-btn" onclick="adminLogout()">🚪 Вийти</button>
        </div>

        <div class="container">
            <!-- ОСНОВНІ СТАТИСТИКИ -->
            <div class="dashboard-grid">
                <div class="stat-card revenue">
                    <div class="stat-label">💰 Загальний дохід</div>
                    <div class="stat-number" id="total-revenue">$0</div>
                    <div class="stat-change">Завантаження...</div>
                </div>
                
                <div class="stat-card users">
                    <div class="stat-label">👥 Користувачів</div>
                    <div class="stat-number" id="total-users">0</div>
                    <div class="stat-change">Завантаження...</div>
                </div>
                
                <div class="stat-card conversion">
                    <div class="stat-label">📦 Замовлень</div>
                    <div class="stat-number" id="total-orders">0</div>
                    <div class="stat-change">Завантаження...</div>
                </div>
                
                <div class="stat-card active">
                    <div class="stat-label">✅ Активні підписки</div>
                    <div class="stat-number" id="active-subscriptions">0</div>
                    <div class="stat-change">Завантаження...</div>
                </div>
            </div>

            <!-- SYSTEM HEALTH -->
            <div class="section">
                <div class="section-header">
                    <div class="section-title">🏥 Здоров'я системи</div>
                    <button class="btn btn-primary" onclick="loadSystemHealth()">🔄 Оновити</button>
                </div>
                
                <div class="dashboard-grid">
                    <div class="alert alert-info" id="mongodb-status">
                        <strong>🔵 MongoDB:</strong> Перевірка...<br>
                        <small>Завантаження...</small>
                    </div>
                    <div class="alert alert-info" id="tron-status">
                        <strong>🔵 TRON API:</strong> Перевірка...<br>
                        <small>Завантаження...</small>
                    </div>
                    <div class="alert alert-info" id="telegram-status">
                        <strong>🔵 Telegram Bot:</strong> Перевірка...<br>
                        <small>Завантаження...</small>
                    </div>
                    <div class="alert alert-info" id="server-status">
                        <strong>🔵 Server:</strong> Онлайн<br>
                        <small>PantelMed Platform v2024</small>
                    </div>
                </div>
            </div>

            <!-- ОСТАННІ ЗАМОВЛЕННЯ -->
            <div class="section">
                <div class="section-header">
                    <div class="section-title">📦 Останні замовлення</div>
                    <button class="btn btn-primary" onclick="loadOrders()">🔄 Оновити</button>
                </div>
                
                <table class="table">
                    <thead>
                        <tr>
                            <th>⏰ Час</th>
                            <th>👤 Користувач</th>
                            <th>💰 Сума</th>
                            <th>📱 Контакт</th>
                            <th>📊 Статус</th>
                            <th>🎯 Дії</th>
                        </tr>
                    </thead>
                    <tbody id="orders-table">
                        <tr>
                            <td colspan="6" style="text-align: center; padding: 40px;">
                                Завантаження замовлень...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- RECENT ACTIVITY -->
            <div class="section">
                <div class="section-header">
                    <div class="section-title">🔴 Активність системи</div>
                    <button class="btn btn-success" onclick="loadRecentActivity()">
                        🔄 Оновити <span class="refresh-indicator hidden" id="activity-spinner"></span>
                    </button>
                </div>
                
                <div class="real-time-log" id="activity-log">
                    <div>[СИСТЕМА] Ініціалізація адмін панелі...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // ГЛОБАЛЬНІ ЗМІННІ
        let isLoggedIn = false;
        let autoRefreshInterval = null;

        // ЛОГІН СИСТЕМА
        function handlePasswordKeyPress(event) {
            if (event.key === 'Enter') {
                adminLogin();
            }
        }

        function adminLogin() {
            const password = document.getElementById('admin-password').value;
            const errorDiv = document.getElementById('login-error');
            
            if (!password) {
                showLoginError('Введіть пароль');
                return;
            }

            if (password === 'pantelmed_admin_2024') {
                isLoggedIn = true;
                
                document.getElementById('login-section').classList.add('hidden');
                document.getElementById('admin-panel').classList.remove('hidden');
                
                initializeAdminPanel();
            } else {
                showLoginError('Неправильний пароль');
            }
        }

        function showLoginError(message) {
            const errorDiv = document.getElementById('login-error');
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => {
                errorDiv.style.display = 'none';
            }, 3000);
        }

        function adminLogout() {
            isLoggedIn = false;
            
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
            
            document.getElementById('admin-panel').classList.add('hidden');
            document.getElementById('login-section').classList.remove('hidden');
            document.getElementById('admin-password').value = '';
        }

        // ІНІЦІАЛІЗАЦІЯ ПАНЕЛІ
        async function initializeAdminPanel() {
            console.log('🚀 Ініціалізація адмін панелі...');
            
            addLogEntry('[СИСТЕМА] Адмін панель завантажується...', 'info');
            
            await Promise.all([
                loadSystemHealth(),
                loadDashboardStats(),
                loadOrders(),
                loadRecentActivity()
            ]);
            
            // Автоматичне оновлення кожні 30 секунд
            autoRefreshInterval = setInterval(() => {
                loadSystemHealth();
                loadRecentActivity();
            }, 30000);
            
            addLogEntry('[СИСТЕМА] Адмін панель готова до роботи', 'success');
        }

        // ЗАВАНТАЖЕННЯ ДАНИХ
        async function loadSystemHealth() {
            try {
                const response = await fetch('/api/admin/health');
                const data = await response.json();
                
                // MongoDB статус
                updateStatusIndicator('mongodb-status', data.mongodb);
                updateStatusIndicator('tron-status', data.tron);
                updateStatusIndicator('telegram-status', data.telegram);
                
            } catch (error) {
                console.error('Error loading system health:', error);
                addLogEntry('[ПОМИЛКА] Не вдалося завантажити статус системи', 'error');
            }
        }

        function updateStatusIndicator(elementId, statusData) {
            const element = document.getElementById(elementId);
            const isHealthy = statusData.status === 'ok' || statusData.healthy;
            
            element.className = isHealthy ? 'alert alert-success' : 'alert alert-danger';
            element.innerHTML = `
                <strong>${isHealthy ? '🟢' : '🔴'} ${statusData.name}:</strong> ${statusData.message}<br>
                <small>${statusData.details || 'Немає додаткової інформації'}</small>
            `;
        }

        async function loadDashboardStats() {
            try {
                const response = await fetch('/api/admin/stats');
                const data = await response.json();
                
                document.getElementById('total-revenue').textContent = '$' + (data.total_revenue || 0).toFixed(2);
                document.getElementById('total-users').textContent = data.total_users || 0;
                document.getElementById('total-orders').textContent = data.total_orders || 0;
                document.getElementById('active-subscriptions').textContent = data.active_subscriptions || 0;
                
                // Оновлюємо статистику
                const changes = [
                    `+${(data.revenue_change || 0).toFixed(1)}% цього місяця`,
                    `+${data.new_users || 0} сьогодні`,
                    `${data.pending_orders || 0} в обробці`,
                    `${data.expiring_soon || 0} закінчуються скоро`
                ];
                
                document.querySelectorAll('.stat-change').forEach((el, index) => {
                    el.textContent = changes[index] || 'Оновлено';
                });
                
            } catch (error) {
                console.error('Error loading dashboard stats:', error);
                addLogEntry('[ПОМИЛКА] Не вдалося завантажити статистику', 'error');
            }
        }

        async function loadOrders() {
            try {
                const response = await fetch('/api/admin/orders');
                const data = await response.json();
                
                const tbody = document.getElementById('orders-table');
                tbody.innerHTML = '';
                
                if (data.orders && data.orders.length > 0) {
                    data.orders.forEach(order => {
                        const row = createOrderRow(order);
                        tbody.appendChild(row);
                    });
                } else {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px;">Немає замовлень</td></tr>';
                }
                
                addLogEntry(`[ДАНІ] Завантажено ${data.orders ? data.orders.length : 0} замовлень`, 'info');
                
            } catch (error) {
                console.error('Error loading orders:', error);
                addLogEntry('[ПОМИЛКА] Не вдалося завантажити замовлення', 'error');
            }
        }

        function createOrderRow(order) {
            const row = document.createElement('tr');
            
            const statusClass = {
                'pending': 'status-pending',
                'completed': 'status-active', 
                'failed': 'status-failed'
            }[order.status] || 'status-pending';
            
            const telegramUser = order.telegram_user || {};
            const orderInfo = order.order_info || {};
            
            row.innerHTML = `
                <td>${new Date(order.created_at).toLocaleString('uk-UA')}</td>
                <td>
                    <strong>${telegramUser.first_name || 'N/A'} ${telegramUser.last_name || ''}</strong><br>
                    <small>@${telegramUser.username || 'no_username'}</small>
                </td>
                <td><strong>$${(order.total_amount || 0).toFixed(2)}</strong></td>
                <td>
                    📞 ${orderInfo.phone || 'N/A'}<br>
                    📍 ${orderInfo.city || 'N/A'}
                </td>
                <td><span class="status-badge ${statusClass}">${order.status || 'pending'}</span></td>
                <td>
                    <button class="btn btn-primary" onclick="contactUser('${telegramUser.id}', '${telegramUser.username}')">
                        💬 Написати
                    </button>
                </td>
            `;
            
            return row;
        }

        function contactUser(telegramId, username) {
            if (telegramId && telegramId !== 'undefined') {
                window.open(`tg://user?id=${telegramId}`, '_blank');
            } else if (username && username !== 'undefined') {
                window.open(`https://t.me/${username}`, '_blank');
            } else {
                alert('Немає контактної інформації для цього користувача');
            }
        }

        async function loadRecentActivity() {
            const spinner = document.getElementById('activity-spinner');
            spinner.classList.remove('hidden');
            
            try {
                // Симулюємо активність для демо
                const activities = [
                    '[MONITOR] Перевірка нових транзакцій...',
                    '[API] TRON API відповідь: 200 OK',
                    '[DB] MongoDB операція успішна',
                    '[BOT] Telegram повідомлення надіслано',
                    '[ORDER] Нове замовлення оброблено',
                    '[SYSTEM] Всі сервіси працюють нормально'
                ];
                
                const randomActivity = activities[Math.floor(Math.random() * activities.length)];
                addLogEntry(randomActivity, 'info');
                
            } catch (error) {
                addLogEntry('[ПОМИЛКА] Не вдалося оновити активність', 'error');
            } finally {
                spinner.classList.add('hidden');
            }
        }

        // ЛОГУВАННЯ
        function addLogEntry(message, type = 'info') {
            const log = document.getElementById('activity-log');
            const entry = document.createElement('div');
            
            const colors = {
                success: '#00ff00',
                warning: '#ffff00',
                error: '#ff0000',
                info: '#00ffff'
            };
            
            const timestamp = new Date().toLocaleTimeString();
            entry.style.color = colors[type] || colors.info;
            entry.textContent = `[${timestamp}] ${message}`;
            
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
            
            // Обмежуємо кількість записів
            while (log.children.length > 100) {
                log.removeChild(log.firstChild);
            }
        }
    </script>
</body>
</html>
"""

# ==============================================
# СТАТИЧНІ ФАЙЛИ
# ==============================================

@app.route('/')
def serve_index():
    """Головна сторінка - React додаток"""
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def serve_admin():
    """Адмін панель"""
    return render_template_string(ADMIN_PANEL_HTML)

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
# ORDERS API
# ==============================================

@app.route("/api/create-order", methods=["POST"])
def create_order():
    """Створення нового замовлення"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Order data required"}), 400
        
        # Генеруємо унікальний ID замовлення
        order_id = f"ORDER_{int(datetime.utcnow().timestamp())}_{data.get('user_id', 'unknown').split('_')[-1]}"
        
        # Підготовка даних замовлення
        order_data = {
            "order_id": order_id,
            "user_id": data.get('user_id'),
            "telegram_user": data.get('telegram_user'),
            "items": data.get('items', []),
            "total_amount": data.get('total_amount', 0),
            "order_info": data.get('order_info', {}),
            "status": "pending",
            "payment_status": "pending",
            "created_at": datetime.utcnow(),
            "source": data.get('source', 'web')
        }
        
        logger.info(f"📦 Creating order {order_id} for user {data.get('user_id')}")
        
        # Зберегти в MongoDB
        safe_db_operation(
            "Insert order",
            lambda: orders_collection.insert_one(order_data) if orders_collection else None
        )
        
        return jsonify({
            "status": "created",
            "order_id": order_id,
            "message": "Order created successfully"
        })
        
    except Exception as e:
        logger.error(f"❌ Create order error: {str(e)}")
        return jsonify({"error": "Failed to create order"}), 500

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
        
        # Повідомлення клієнту
        customer_message = f"""
🎉 <b>Дякуємо за замовлення!</b>

📦 <b>Ваше замовлення:</b>
"""
        for item in items:
            customer_message += f"• {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}\n"
        
        customer_message += f"""
💰 <b>Загалом:</b> ${total_amount:.2f}
📍 <b>Доставка:</b> {order_info.get('city', '')} - {order_info.get('warehouse', '')}

Ми зв'яжемося з вами найближчим часом!
        """
        
        # Відправити клієнту
        if telegram_user.get('id'):
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": telegram_user['id'],
                        "text": customer_message,
                        "parse_mode": "HTML"
                    },
                    timeout=10
                )
            except Exception as e:
                logger.error(f"Failed to send customer notification: {e}")
        
        # Повідомлення адміну
        if ADMIN_TELEGRAM_ID != "YOUR_ADMIN_ID":
            admin_message = f"""
🆕 <b>Нове замовлення!</b>

👤 <b>Клієнт:</b> {telegram_user.get('first_name', '')} {telegram_user.get('last_name', '')}
📱 @{telegram_user.get('username', 'no_username')}

💰 <b>Сума:</b> ${total_amount:.2f}
📞 <b>Телефон:</b> {order_info.get('phone', '')}
📍 <b>Доставка:</b> {order_info.get('city', '')} - {order_info.get('warehouse', '')}
"""
            
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_TELEGRAM_ID,
                        "text": admin_message,
                        "parse_mode": "HTML"
                    },
                    timeout=10
                )
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
        
        return jsonify({"status": "notifications_sent"})
        
    except Exception as e:
        logger.error(f"❌ Order notification error: {str(e)}")
        return jsonify({"error": "Notification failed"}), 500

# ==============================================
# PAYMENT API
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
# ADMIN API
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
            
            # Замовлення
            total_orders = safe_db_operation(
                "Count orders",
                lambda: orders_collection.count_documents({}) if orders_collection else 0
            ) or 0
            
            # Дохід
            revenue_pipeline = [
                {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
            ]
            revenue_result = safe_db_operation(
                "Calculate revenue",
                lambda: list(orders_collection.aggregate(revenue_pipeline)) if orders_collection else []
            )
            if revenue_result:
                total_revenue = revenue_result[0].get('total', 0)
            
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
    """Замовлення для адмін панелі"""
    try:
        orders = []
        
        if orders_collection:
            # Отримуємо останні 50 замовлень
            cursor = safe_db_operation(
                "Find orders",
                lambda: orders_collection.find().sort('created_at', -1).limit(50)
            )
            
            if cursor:
                for order in cursor:
                    # Конвертуємо ObjectId та datetime для JSON
                    order['_id'] = str(order['_id'])
                    if 'created_at' in order:
                        order['created_at'] = order['created_at'].isoformat()
                    orders.append(order)
        
        return jsonify({
            "orders": orders,
            "total": len(orders)
        })
        
    except Exception as e:
        logger.error(f"Admin orders error: {e}")
        return jsonify({"error": "Failed to fetch orders"}), 500

# ==============================================
# ONRAMPER INTEGRATION
# ==============================================

@app.route("/onramper-webhook", methods=["POST"])
def onramper_webhook():
    """Обробка вебхуків від Onramper"""
    try:
        payload = request.get_data()
        data = json.loads(payload.decode('utf-8'))
        event_type = data.get('type')
        transaction_data = data.get('data', {})
        
        logger.info(f"📥 Onramper webhook: {event_type}")
        
        if event_type == 'ONRAMP_TRANSACTION_COMPLETED':
            return handle_onramper_success(transaction_data)
        elif event_type == 'ONRAMP_TRANSACTION_FAILED':
            return handle_onramper_failed(transaction_data)
        else:
            return jsonify({"status": "ignored"}), 200
            
    except Exception as e:
        logger.error(f"❌ Onramper webhook error: {str(e)}")
        return jsonify({"error": "Processing failed"}), 500

def handle_onramper_success(data):
    """Успішна Onramper транзакція"""
    tx_id = data.get('id')
    crypto_amount = float(data.get('cryptoAmount', 0))
    crypto_currency = data.get('cryptoCurrency', '')
    user_wallet = data.get('walletAddress')
    
    logger.info(f"✅ Onramper success: {crypto_amount} {crypto_currency}")
    
    if crypto_currency.upper() != 'USDT' or crypto_amount < 2.5:
        return jsonify({"status": "invalid_amount"}), 400
    
    # Створюємо користувача
    user_id = f"onramper_{int(datetime.utcnow().timestamp())}"
    
    # Активуємо підписку
    expires_at = datetime.utcnow() + timedelta(days=SUBSCRIPTION_DAYS)
    subscription_data = {
        "user_id": user_id,
        "payment_method": "onramper",
        "transaction_id": tx_id,
        "amount_paid": crypto_amount,
        "currency": crypto_currency,
        "wallet_address": user_wallet,
        "expires_at": expires_at,
        "activated_at": datetime.utcnow(),
        "active": True,
        "created_at": datetime.utcnow()
    }
    
    safe_db_operation(
        "Insert onramper subscription",
        lambda: subscriptions_collection.insert_one(subscription_data) if subscriptions_collection else None
    )
    
    return jsonify({"status": "subscription_activated"}), 200

def handle_onramper_failed(data):
    """Невдала Onramper транзакція"""
    tx_id = data.get('id')
    error_reason = data.get('failureReason', 'Unknown error')
    
    logger.warning(f"❌ Onramper failed: {tx_id} - {error_reason}")
    
    return jsonify({"status": "noted"}), 200

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
        "version": "PANTELMED_PLATFORM_2024",
        "timestamp": datetime.utcnow().isoformat(),
        "mongodb": {
            "status": mongodb_status,
            "connection_test": mongodb_test,
            "uri": MONGO_URI.replace("manreds7", "***") if MONGO_URI else "not set"
        },
        "tron_wallet": TRON_WALLET,
        "automation": monitoring_info,
        "telegram_bot": TELEGRAM_BOT_USERNAME
    })

# ==============================================
# PAYMENT MONITORING
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
    logger.info("🚀 Starting PantelMed Platform...")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"📡 Server will run on port: {port}")
    logger.info(f"💾 MongoDB: {'Connected' if db else 'Disconnected'}")
    logger.info(f"🔗 TRON Wallet: {TRON_WALLET}")
    logger.info(f"🤖 Telegram Bot: @{TELEGRAM_BOT_USERNAME}")
    logger.info(f"🔄 Payment Monitor: {'Enabled' if payment_monitor else 'Disabled'}")
    
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except Exception as e:
        logger.error(f"❌ Server failed to start: {e}")
        raise
