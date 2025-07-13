#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PantelMed Platform - Startup Script
Автоматична перевірка та ініціалізація системи
"""

import os
import sys
import subprocess
import json
import time
from pathlib import Path
from urllib.parse import urlparse
import requests

# Кольорові виводи
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_colored(message, color=Colors.WHITE):
    """Кольоровий вивід"""
    print(f"{color}{message}{Colors.ENDC}")

def print_header(title):
    """Красивий заголовок"""
    print_colored("\n" + "="*60, Colors.CYAN)
    print_colored(f"🏥 PantelMed Platform - {title}", Colors.BOLD + Colors.CYAN)
    print_colored("="*60, Colors.CYAN)

def print_step(step_num, description):
    """Крок з нумерацією"""
    print_colored(f"\n📋 Крок {step_num}: {description}", Colors.BLUE)

def print_success(message):
    """Успішне повідомлення"""
    print_colored(f"✅ {message}", Colors.GREEN)

def print_error(message):
    """Повідомлення про помилку"""
    print_colored(f"❌ {message}", Colors.RED)

def print_warning(message):
    """Попередження"""
    print_colored(f"⚠️  {message}", Colors.YELLOW)

def print_info(message):
    """Інформаційне повідомлення"""
    print_colored(f"ℹ️  {message}", Colors.CYAN)

def check_python_version():
    """Перевірка версії Python"""
    print_step(1, "Перевірка версії Python")
    
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print_success(f"Python {version.major}.{version.minor}.{version.micro} ✓")
        return True
    else:
        print_error(f"Потрібен Python 3.8+, знайдено {version.major}.{version.minor}.{version.micro}")
        return False

def check_required_files():
    """Перевірка наявності обов'язкових файлів"""
    print_step(2, "Перевірка файлів проекту")
    
    required_files = [
        'app.py',
        'requirements.txt',
        'index.html',
        'shop.html',
        'style.css',
        '.env.example'
    ]
    
    missing_files = []
    for file in required_files:
        if Path(file).exists():
            print_success(f"{file} ✓")
        else:
            print_error(f"{file} не знайдено")
            missing_files.append(file)
    
    if missing_files:
        print_error(f"Відсутні файли: {', '.join(missing_files)}")
        return False
    
    return True

def check_environment_file():
    """Перевірка .env файлу"""
    print_step(3, "Перевірка змінних середовища")
    
    if not Path('.env').exists():
        print_warning(".env файл не знайдено")
        
        response = input("🔧 Створити .env файл з .env.example? (y/n): ").lower()
        if response == 'y':
            try:
                with open('.env.example', 'r', encoding='utf-8') as src:
                    content = src.read()
                with open('.env', 'w', encoding='utf-8') as dst:
                    dst.write(content)
                print_success(".env файл створено")
                print_warning("⚠️  ВАЖЛИВО: Відредагуйте .env файл з вашими даними!")
                return False  # Потрібно налаштувати
            except Exception as e:
                print_error(f"Помилка створення .env: {e}")
                return False
        else:
            print_error("Неможливо продовжити без .env файлу")
            return False
    
    # Перевірка основних змінних
    required_vars = [
        'MONGO_URI',
        'TELEGRAM_BOT_TOKEN',
        'TRON_WALLET',
        'ADMIN_PASSWORD'
    ]
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or 'your_' in value.lower() or 'change_this' in value.lower():
                missing_vars.append(var)
                print_error(f"{var} не налаштовано")
            else:
                print_success(f"{var} ✓")
        
        if missing_vars:
            print_error(f"Не налаштовані змінні: {', '.join(missing_vars)}")
            print_info("Відредагуйте .env файл з правильними значеннями")
            return False
        
        return True
        
    except ImportError:
        print_warning("python-dotenv не встановлено, пропускаємо перевірку .env")
        return True

def install_dependencies():
    """Встановлення залежностей"""
    print_step(4, "Встановлення Python залежностей")
    
    try:
        # Перевірка віртуального середовища
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            print_success("Віртуальне середовище активовано ✓")
        else:
            print_warning("Віртуальне середовище не активовано")
            response = input("Продовжити без venv? (y/n): ").lower()
            if response != 'y':
                print_info("Створіть та активуйте venv:")
                print_info("python -m venv venv")
                print_info("source venv/bin/activate  # Linux/Mac")
                print_info("venv\\Scripts\\activate     # Windows")
                return False
        
        # Встановлення залежностей
        print_info("Встановлення залежностей...")
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print_success("Залежності встановлено ✓")
            return True
        else:
            print_error(f"Помилка встановлення: {result.stderr}")
            return False
            
    except Exception as e:
        print_error(f"Помилка: {e}")
        return False

def test_database_connection():
    """Тест підключення до MongoDB"""
    print_step(5, "Тестування підключення до MongoDB")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        mongo_uri = os.getenv('MONGO_URI')
        if not mongo_uri or 'your_' in mongo_uri:
            print_warning("MONGO_URI не налаштовано, пропускаємо тест")
            return True
        
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure
        
        print_info("Підключення до MongoDB...")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        
        print_success("MongoDB підключення успішне ✓")
        
        # Перевірка доступу до бази
        db_name = urlparse(mongo_uri).path.lstrip('/')
        if db_name:
            db = client[db_name]
            collections = db.list_collection_names()
            print_info(f"База даних: {db_name}, колекцій: {len(collections)}")
        
        client.close()
        return True
        
    except ImportError:
        print_warning("pymongo не встановлено, пропускаємо тест MongoDB")
        return True
    except ConnectionFailure:
        print_error("Не вдалося підключитися до MongoDB")
        print_info("Перевірте MONGO_URI та доступ до мережі")
        return False
    except Exception as e:
        print_error(f"Помилка MongoDB: {e}")
        return False

def test_telegram_bot():
    """Тест Telegram бота"""
    print_step(6, "Тестування Telegram бота")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token or 'your_' in bot_token:
            print_warning("TELEGRAM_BOT_TOKEN не налаштовано, пропускаємо тест")
            return True
        
        print_info("Тестування Telegram Bot API...")
        response = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data['result']
                print_success(f"Telegram бот активний: @{bot_info['username']} ✓")
                return True
            else:
                print_error(f"Telegram API помилка: {data}")
                return False
        else:
            print_error(f"HTTP помилка: {response.status_code}")
            return False
            
    except ImportError:
        print_warning("requests не встановлено, пропускаємо тест Telegram")
        return True
    except Exception as e:
        print_error(f"Помилка Telegram: {e}")
        return False

def test_tron_api():
    """Тест TRON API"""
    print_step(7, "Тестування TRON API")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        tron_wallet = os.getenv('TRON_WALLET')
        if not tron_wallet or 'your_' in tron_wallet:
            print_warning("TRON_WALLET не налаштовано, пропускаємо тест")
            return True
        
        print_info("Тестування TRON API...")
        url = f"https://api.trongrid.io/v1/accounts/{tron_wallet}/transactions/trc20?limit=1"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print_success("TRON API доступний ✓")
            print_info(f"Гаманець: {tron_wallet[:10]}...{tron_wallet[-10:]}")
            return True
        else:
            print_error(f"TRON API помилка: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Помилка TRON API: {e}")
        return False

def start_application():
    """Запуск додатка"""
    print_step(8, "Запуск PantelMed Platform")
    
    try:
        print_info("Запуск Flask додатка...")
        print_info("URL: http://localhost:10000")
        print_info("Адмін панель: http://localhost:10000/admin")
        print_info("Для зупинки натисніть Ctrl+C")
        
        # Запуск з автоматичним перезавантаженням в dev режимі
        os.environ['FLASK_ENV'] = 'development'
        os.environ['FLASK_DEBUG'] = 'True'
        
        subprocess.run([sys.executable, 'app.py'])
        
    except KeyboardInterrupt:
        print_info("\n👋 Додаток зупинено")
    except Exception as e:
        print_error(f"Помилка запуску: {e}")

def show_quick_commands():
    """Показати корисні команди"""
    print_header("Корисні команди")
    
    commands = [
        ("🚀 Запуск додатка", "python app.py"),
        ("🤖 Запуск Telegram бота", "python telegram_bot.py"),
        ("🐳 Docker запуск", "docker-compose up -d"),
        ("🧪 Тест здоров'я", "curl http://localhost:10000/health"),
        ("📊 Адмін панель", "http://localhost:10000/admin"),
        ("🛒 Магазин БАДів", "http://localhost:10000/shop.html"),
        ("📝 Логи Docker", "docker-compose logs -f"),
        ("🔄 Перезапуск", "docker-compose restart"),
    ]
    
    for desc, cmd in commands:
        print_colored(f"{desc:<25} {Colors.CYAN}{cmd}{Colors.ENDC}", Colors.WHITE)

def main():
    """Головна функція"""
    print_header("Startup Script")
    print_info("Перевірка та ініціалізація PantelMed Platform")
    
    # Виконуємо всі перевірки
    checks = [
        check_python_version,
        check_required_files,
        check_environment_file,
        install_dependencies,
        test_database_connection,
        test_telegram_bot,
        test_tron_api
    ]
    
    failed_checks = 0
    for check in checks:
        if not check():
            failed_checks += 1
    
    print_header("Результат перевірки")
    
    if failed_checks == 0:
        print_success("🎉 Всі перевірки пройдено успішно!")
        print_info("Система готова до запуску")
        
        response = input("\n🚀 Запустити додаток зараз? (y/n): ").lower()
        if response == 'y':
            start_application()
        else:
            show_quick_commands()
            
    elif failed_checks <= 2:
        print_warning(f"⚠️  {failed_checks} перевірок не пройдено")
        print_info("Система частково готова, можна спробувати запуск")
        show_quick_commands()
        
    else:
        print_error(f"❌ {failed_checks} критичних помилок")
        print_info("Виправте помилки перед запуском")
        print_info("\n📖 Детальні інструкції:")
        print_info("- README.md - Загальна документація")
        print_info("- DEPLOYMENT_GUIDE.md - Гайд по розгортанню")
        print_info("- .env.example - Приклад конфігурації")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_info("\n👋 Скрипт перервано користувачем")
    except Exception as e:
        print_error(f"Критична помилка: {e}")
        sys.exit(1)
