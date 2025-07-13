# 🚀 PantelMed Platform - Гайд по розгортанню

Детальні інструкції для розгортання повнофункціональної PantelMed платформи з магазином БАДів та Telegram інтеграцією.

## 📋 Огляд архітектури

```mermaid
graph TB
    TG[Telegram Bot] --> WEB[Web Platform]
    WEB --> MONGO[MongoDB Atlas]
    WEB --> TRON[TRON Blockchain]
    WEB --> REDIS[Redis Cache]
    USERS[Користувачі] --> TG
    USERS --> WEB
    ADMIN[Адміністратор] --> ADMIN_PANEL[Admin Panel]
    ADMIN_PANEL --> WEB
```

## 🎯 Варіанти розгортання

### 1. 🏃‍♂️ Швидкий старт (Render.com)
**Рекомендується для початку**
- ✅ Найпростіше налаштування
- ✅ Автоматичне HTTPS
- ✅ Безкоштовний план доступний
- ❌ Обмеження ресурсів на безкоштовному плані

### 2. 🐳 Docker локально або VPS
**Для повного контролю**
- ✅ Повний контроль над середовищем
- ✅ Можливість масштабування
- ❌ Потребує технічних знань
- ❌ Потрібно налаштовувати SSL

### 3. ☁️ Cloud провайдери (AWS, Google Cloud, Azure)
**Для enterprise рішень**
- ✅ Максимальна надійність
- ✅ Автоматичне масштабування
- ❌ Складність налаштування
- ❌ Вища вартість

---

## 🚀 Метод 1: Розгортання на Render.com

### Крок 1: Підготовка репозиторію

1. **Створіть GitHub репозиторій**
```bash
git init
git add .
git commit -m "Initial PantelMed platform commit"
git branch -M main
git remote add origin https://github.com/yourusername/pantelmed-platform.git
git push -u origin main
```

2. **Переконайтеся, що у вас є всі файли:**
```
pantelmed-platform/
├── app.py                          ✅
├── telegram_bot.py                 ✅
├── index.html                      ✅
├── shop.html                       ✅
├── pay.html                        ✅
├── thankyou.html                   ✅
├── thankyou_supplements.html       ✅
├── admin.html                      ✅
├── style.css                       ✅
├── requirements.txt                ✅
├── .env.example                    ✅
├── README.md                       ✅
├── DEPLOYMENT_GUIDE.md             ✅
└── .gitignore                      📝 (створити)
```

3. **Створіть .gitignore файл:**
```gitignore
# Environment variables
.env
.env.local
.env.production

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
pip-log.txt
pip-delete-this-directory.txt

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Database
*.db
*.sqlite3

# Uploads
uploads/

# Cache
.cache/
```

### Крок 2: Налаштування зовнішніх сервісів

#### 2.1 MongoDB Atlas

1. **Реєстрація та створення кластера:**
   - Йдіть на https://cloud.mongodb.com
   - Створіть безкоштовний акаунт
   - Створіть новий кластер (M0 Sandbox - безкоштовний)
   - Назвіть кластер: `pantelmed-cluster`

2. **Налаштування доступу:**
   ```
   Database Access → Add New Database User
   - Username: pantelmed
   - Password: [генеруйте сильний пароль]
   - Built-in Role: Read and write to any database
   ```

3. **Налаштування мережі:**
   ```
   Network Access → Add IP Address
   - Add Current IP Address (для розробки)
   - Allow Access from Anywhere (для Render.com)
   ```

4. **Отримання Connection String:**
   ```
   Clusters → Connect → Connect your application
   - Driver: Python
   - Version: 3.11 or later
   - Copy connection string
   ```

#### 2.2 Telegram Bot

1. **Створення бота:**
   ```
   Напишіть @BotFather в Telegram:
   /newbot
   Назва: PantelMed Bot
   Username: pantelmed_bot (або ваш унікальний)
   
   Збережіть отриманий TOKEN!
   ```

2. **Налаштування Login Widget:**
   ```
   /setdomain
   [ваш майбутній домен Render]
   
   /setcommands
   start - Головне меню
   help - Довідка
   status - Статус підписки
   shop - Магазин БАДів
   support - Підтримка
   ```

#### 2.3 TRON Гаманець

1. **Створіть TRON гаманець:**
   - Використайте TronLink або інший надійний гаманець
   - Переконайтеся, що підтримує TRC-20 токени
   - Збережіть адресу гаманця

2. **Тестування (опціонально):**
   - Отримайте тестові TRX з faucet
   - Переконайтеся, що можете отримувати USDT

### Крок 3: Розгортання на Render.com

#### 3.1 Створення Web Service

1. **Підключення до Render:**
   - Йдіть на https://render.com
   - Увійдіть через GitHub
   - New → Web Service
   - Connect your GitHub repository

2. **Налаштування сервісу:**
   ```
   Name: pantelmed-platform
   Environment: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn app:app --bind 0.0.0.0:$PORT --workers 4
   Instance Type: Free (або Professional)
   ```

#### 3.2 Налаштування змінних середовища

```bash
# Основні налаштування
FLASK_ENV=production
PORT=10000

# MongoDB
MONGO_URI=mongodb+srv://pantelmed:password@pantelmed-cluster.xxxxx.mongodb.net/pantelmed?retryWrites=true&w=majority

# Telegram
TELEGRAM_BOT_TOKEN=1234567890:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPPQQrr
TELEGRAM_BOT_USERNAME=pantelmed_bot
ADMIN_TELEGRAM_ID=123456789

# TRON
TRON_WALLET=TQeHa8VdwfyybxtioW4ggbnDC1rbWe8nFa
MIN_AMOUNT=2.6
MIN_AMOUNT_TEST=0.5
SUBSCRIPTION_DAYS=30

# Безпека
ADMIN_PASSWORD=your_strong_password_here
```

#### 3.3 Розгортання Telegram Bot (окремо)

1. **Створіть другий Web Service:**
   ```
   Name: pantelmed-telegram-bot
   Environment: Python 3
   Build Command: pip install python-telegram-bot[all] aiohttp python-dotenv
   Start Command: python telegram_bot.py
   Instance Type: Free
   ```

2. **Налаштуйте змінні:**
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token
   PLATFORM_URL=https://pantelmed-platform.onrender.com
   ADMIN_TELEGRAM_ID=123456789
   ```

### Крок 4: Тестування

1. **Перевірте Web платформу:**
   - Відкрийте ваш Render URL
   - Перевірте /health endpoint
   - Спробуйте увійти в адмін панель

2. **Перевірте Telegram бота:**
   - Напишіть /start боту
   - Перевірте чи працюють кнопки
   - Спробуйте перейти на веб платформу

3. **Перевірте інтеграцію:**
   - Спробуйте зробити тестове замовлення
   - Перевірте чи приходять сповіщення

---

## 🐳 Метод 2: Docker розгортання

### Крок 1: Підготовка середовища

1. **Встановіть Docker та Docker Compose:**
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

2. **Клонуйте репозиторій:**
```bash
git clone https://github.com/yourusername/pantelmed-platform.git
cd pantelmed-platform
```

### Крок 2: Конфігурація

1. **Створіть .env файл:**
```bash
cp .env.example .env
nano .env
```

2. **Заповніть всі необхідні змінні** (див. розділ вище)

### Крок 3: Запуск

#### Простий запуск (тільки основні сервіси):
```bash
docker-compose up -d web telegram-bot redis
```

#### Повний запуск з моніторингом:
```bash
docker-compose --profile monitoring up -d
```

#### Розробка з локальною базою:
```bash
docker-compose --profile development up -d
```

### Крок 4: Налаштування Nginx (опціонально)

Для production з SSL:

1. **Створіть nginx.conf:**
```nginx
events {
    worker_connections 1024;
}

http {
    upstream pantelmed_app {
        server web:10000;
    }

    server {
        listen 80;
        server_name yourdomain.com www.yourdomain.com;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl;
        server_name yourdomain.com www.yourdomain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;

        location / {
            proxy_pass http://pantelmed_app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

2. **Запуск з Nginx:**
```bash
docker-compose --profile production-nginx up -d
```

---

## ⚙️ Метод 3: VPS розгортання

### Крок 1: Підготовка сервера

1. **Оновлення системи:**
```bash
sudo apt update && sudo apt upgrade -y
```

2. **Встановлення залежностей:**
```bash
sudo apt install -y python3 python3-pip python3-venv nginx redis-server git curl
```

3. **Створення користувача:**
```bash
sudo adduser pantelmed
sudo usermod -aG sudo pantelmed
su - pantelmed
```

### Крок 2: Налаштування додатка

1. **Клонування та підготовка:**
```bash
git clone https://github.com/yourusername/pantelmed-platform.git
cd pantelmed-platform

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Конфігурація:**
```bash
cp .env.example .env
nano .env
# Заповніть змінні середовища
```

### Крок 3: Налаштування systemd сервісів

1. **Web платформа:**
```bash
sudo nano /etc/systemd/system/pantelmed-web.service
```

```ini
[Unit]
Description=PantelMed Web Platform
After=network.target

[Service]
User=pantelmed
Group=pantelmed
WorkingDirectory=/home/pantelmed/pantelmed-platform
Environment=PATH=/home/pantelmed/pantelmed-platform/venv/bin
ExecStart=/home/pantelmed/pantelmed-platform/venv/bin/gunicorn --workers 4 --bind 0.0.0.0:10000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

2. **Telegram Bot:**
```bash
sudo nano /etc/systemd/system/pantelmed-bot.service
```

```ini
[Unit]
Description=PantelMed Telegram Bot
After=network.target

[Service]
User=pantelmed
Group=pantelmed
WorkingDirectory=/home/pantelmed/pantelmed-platform
Environment=PATH=/home/pantelmed/pantelmed-platform/venv/bin
ExecStart=/home/pantelmed/pantelmed-platform/venv/bin/python telegram_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

3. **Запуск сервісів:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable pantelmed-web pantelmed-bot
sudo systemctl start pantelmed-web pantelmed-bot
```

### Крок 4: Налаштування Nginx

1. **Конфігурація сайту:**
```bash
sudo nano /etc/nginx/sites-available/pantelmed
```

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /home/pantelmed/pantelmed-platform/static;
    }
}
```

2. **Активація:**
```bash
sudo ln -s /etc/nginx/sites-available/pantelmed /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

3. **SSL сертифікат (Let's Encrypt):**
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

---

## 🔧 Налаштування після розгортання

### 1. Налаштування домену в Telegram

```
@BotFather → /setdomain → yourdomain.com
```

### 2. Тестування всіх функцій

1. **Web платформа:**
   - [ ] Головна сторінка відкривається
   - [ ] Telegram авторизація працює
   - [ ] Магазин БАДів відображається
   - [ ] Можна додавати товари в кошик
   - [ ] Форма замовлення працює
   - [ ] Адмін панель доступна

2. **Telegram Bot:**
   - [ ] Відповідає на /start
   - [ ] Кнопки працюють
   - [ ] WebApp відкривається
   - [ ] Переходи на сайт працюють

3. **Інтеграція:**
   - [ ] Дані користувача синхронізуються
   - [ ] Замовлення зберігаються в базі
   - [ ] Сповіщення надходять
   - [ ] Платежі відстежуються

### 3. Моніторинг та логування

1. **Перегляд логів:**
```bash
# Docker
docker-compose logs -f web
docker-compose logs -f telegram-bot

# systemd
sudo journalctl -f -u pantelmed-web
sudo journalctl -f -u pantelmed-bot
```

2. **Моніторинг здоров'я:**
```bash
# Health check
curl https://yourdomain.com/health

# Admin stats
curl https://yourdomain.com/api/admin/health
```

---

## 🔒 Безпека та оптимізація

### 1. Безпека

1. **Firewall:**
```bash
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
```

2. **Fail2ban:**
```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
```

3. **Регулярні оновлення:**
```bash
# Створіть cron job для оновлень
sudo crontab -e
# Додайте: 0 3 * * 0 apt update && apt upgrade -y
```

### 2. Оптимізація

1. **Redis кеш:**
   - Налаштуйте Redis для кешування сесій
   - Використовуйте для кешування API відповідей

2. **Backup:**
```bash
# Скрипт backup MongoDB
#!/bin/bash
BACKUP_DIR="/backup/mongodb"
DATE=$(date +%Y%m%d_%H%M%S)
mongodump --uri="$MONGO_URI" --out="$BACKUP_DIR/$DATE"
```

3. **Автоматичне масштабування:**
   - Використовуйте Docker Swarm або Kubernetes
   - Налаштуйте горизонтальне масштабування

---

## 🚨 Усунення проблем

### Частіі проблеми:

1. **"Bot token invalid"**
   - Перевірте TELEGRAM_BOT_TOKEN
   - Переконайтеся, що токен не має зайвих пробілів

2. **"MongoDB connection failed"**
   - Перевірте MONGO_URI
   - Переконайтеся, що IP додано в whitelist
   - Перевірте логін/пароль

3. **"TRON API timeout"**
   - Перевірте інтернет з'єднання
   - TRON API може бути тимчасово недоступним

4. **"Orders not saving"**
   - Перевірте права запису в MongoDB
   - Перевірте логи web сервісу

### Корисні команди:

```bash
# Перезапуск сервісів
sudo systemctl restart pantelmed-web pantelmed-bot

# Перевірка статусу
sudo systemctl status pantelmed-web

# Переcтворення контейнерів
docker-compose restart web telegram-bot

# Перевірка підключення до БД
python -c "from pymongo import MongoClient; client = MongoClient('your_mongo_uri'); print(client.list_database_names())"
```

---

## 📞 Підтримка

Якщо виникли проблеми з розгортанням:

1. Перевірте логи сервісів
2. Переконайтеся, що всі змінні середовища налаштовані
3. Зверніться до документації сервісів (Render, MongoDB Atlas)
4. Створіть issue в GitHub репозиторії

---

**Успішного розгортання! 🚀**

*PantelMed Platform Team* 🏥💚
