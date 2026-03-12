# Sharks Padel MVP (standalone)

## Что изменено после security-аудита
- Добавлена глобальная CSRF-защита для всех POST-форм.
- Убран небезопасный runtime: приложение не стартует без `SECRET_KEY`, debug выключен по умолчанию.
- Убран вывод тестовых логинов/паролей из UI.
- Добавлен безопасный bootstrap первого администратора: через env или CLI-команду.
- Чеки перенесены в приватное хранилище (вне `static`), доступ к файлам только через защищенный staff-endpoint.
- Усилена валидация файлов чеков (расширение + сигнатура JPEG/PNG/PDF).
- Статусы заявок централизованы, ограничены whitelist и проверкой допустимых переходов.
- Усилена серверная валидация реквизитов, ссылок, цен и связности гео-сущностей.
- Добавлен idempotency-токен на шаге загрузки чека для защиты от дублей.
- Убраны hardcoded `role_id`, добавлен базовый audit log админских действий.

## Архитектура и стек
- Backend: Flask + SQLAlchemy + Flask-Login + Flask-WTF (CSRF)
- DB: SQLite (MVP), совместимо с PostgreSQL через `DATABASE_URL`
- UI: Jinja2 + CSS
- Файлы чеков: приватный каталог (`PROOF_UPLOAD_FOLDER`), не public static

## Модели
Ключевые сущности:
- `users`, `roles`
- `countries`, `cities`, `courts`, `time_slots`, `prices`
- `payment_methods`, `payment_accounts`, `crypto_accounts`
- `bookings`, `payment_proofs`
- `payment_links`, `tournaments`
- `audit_logs`

## Основные URL (сохранены)
### Public
- `GET /` — выбор игры
- `POST /calculate` — расчёт цены
- `GET /pay` — выбор способа оплаты
- `POST /pay/select` — выбор реквизитов
- `GET /proof` / `POST /proof` — загрузка чека и создание заявки
- `GET /success/<id>` — подтверждение отправки
- `GET /l/<token>` — персональная/турнирная ссылка

### Admin
- `GET/POST /admin/login`
- `GET /admin`
- `GET /admin/bookings`
- `GET/POST /admin/bookings/<id>` + смена статуса
- `GET /admin/proofs/<proof_id>` — защищенный доступ к чеку
- `GET/POST /admin/requisites`
- `GET/POST /admin/links`
- `GET/POST /admin/geo/*`
- `GET/POST /admin/prices`
- `GET/POST /admin/users`

## Запуск
```bash
cp .env.example .env
# обязательно задайте SECRET_KEY
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
python app.py
```

## Создание первого администратора
### Вариант 1: через env при старте
```bash
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export BOOTSTRAP_ADMIN_PASSWORD=SuperSecure123
python app.py
```
Пользователь создается только если такого email ещё нет.

### Вариант 2: через CLI (рекомендуется)
```bash
flask --app app:create_app create-admin --email admin@example.com --password SuperSecure123
```

## ENV-переменные
- `SECRET_KEY` (обязательно)
- `DATABASE_URL` (опционально, по умолчанию SQLite)
- `PROOF_UPLOAD_FOLDER` (опционально)
- `FLASK_DEBUG` (`0`/`1`, по умолчанию `0`)
- `BOOTSTRAP_ADMIN_EMAIL` (опционально)
- `BOOTSTRAP_ADMIN_PASSWORD` (опционально)

## Ограничения MVP, оставленные осознанно
- Нет автоматических платежных интеграций (по бизнес-требованию).
- Нет полноценной системы миграций в этой итерации (подготовка к следующему этапу).
