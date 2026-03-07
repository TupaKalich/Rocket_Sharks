# Sharks Padel MVP (standalone)

## 1) Архитектура и стек

**Подход:** отдельный монолитный сервис с чистым разделением на публичный контур и админ-контур. Сервис независим от обменника, может работать на `/padel` через reverse proxy или на поддомене `padel.*`.

- **Backend:** Flask + SQLAlchemy
- **DB:** SQLite (для MVP), совместимо с PostgreSQL через `DATABASE_URL`
- **Auth:** Flask-Login, роли `admin` и `operator`
- **Storage:** локальная файловая система (`app/static/uploads`) для чеков
- **UI:** серверные шаблоны Jinja2 + адаптивный CSS

Ключевые ограничения MVP соблюдены:
- автоматических интеграций с платежками нет;
- показываем реквизиты;
- пользователь загружает чек;
- оператор/админ вручную подтверждает или отклоняет.

## 2) Модели данных

Реализованы сущности:
- `users`, `roles`
- `countries`, `cities`, `courts`, `time_slots`, `prices`
- `payment_methods`, `payment_accounts`, `crypto_accounts`
- `bookings`, `payment_proofs`
- `payment_links`, `tournaments`

Схема покрывает сценарии:
- обычная запись;
- персональная ссылка с фиксированными параметрами;
- турнирная ссылка с фиксированной стоимостью.

## 3) Страницы

### Public
1. `/` — выбор страны/города/корта/даты/времени
2. `/pay` — выбор метода оплаты
3. `/proof` — реквизиты + загрузка чека
4. `/success/<id>` — заявка создана
5. `/l/<token>` — персональная ссылка
6. `/l/<token>` (тип tournament) — турнирный сценарий

### Admin
1. `/admin/login` — авторизация
2. `/admin` — дашборд
3. `/admin/bookings` — список заявок
4. `/admin/bookings/<id>` — карточка + смена статуса
5. `/admin/geo` — страны/города/корты
6. `/admin/prices` — цены
7. `/admin/requisites` — методы и реквизиты
8. `/admin/links` — персональные и турнирные ссылки
9. `/admin/users` — управление операторами

## 4) API / серверная логика

MVP построен на серверных HTML endpoint-ах.

Основные потоки:
- `POST /calculate` — валидация выбора + расчет цены по прайсу
- `POST /pay/select` — выбор метода, обязательная биржа для crypto
- `POST /proof` — загрузка чека (jpg/png/pdf), фиксация суммы и создание заявки
- `POST /admin/bookings/<id>/status` — ручной review платежа
- `POST /admin/links` — создание персональных/турнирных ссылок

Защиты:
- серверная валидация обязательных шагов;
- ограничение форматов чека;
- защита от повторной отправки за счет очистки draft после создания заявки.

## 5) Структура проекта

```
.
├── app.py
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   ├── static/
│   │   ├── styles.css
│   │   └── uploads/
│   └── templates/
│       ├── base.html
│       ├── public/
│       └── admin/
```

## 6) Реализация MVP

### Функционально готово
- полноценный user flow записи и ручной оплаты;
- загрузка чека и создание заявки со статусом `pending_confirmation`;
- админ/оператор видят заявки и меняют статус (`new`, `pending_confirmation`, `confirmed`, `rejected`, `canceled`);
- раздельные роли;
- управление справочниками, ценами, реквизитами;
- создание персональных/турнирных ссылок.

### Дефолтные данные
- Country: Thailand
- City: Phuket
- Court: Sharks Padel Court
- Payment methods: SBP / Thai QR / Crypto
- Crypto exchanges: Bybit / HTX
- Admin: `admin@padel.local` / `admin123`
- Operator: `operator@padel.local` / `operator123`

## 7) Слабые места постановки и pragmatic MVP-решения

1. **Нет четкого требования по часовым поясам и слотам пересечений.**
   - Сейчас слот выбирается из справочника; конфликтов брони на один слот не проверяем (можно добавить этапом 2).

2. **Нет SLA и процесса review.**
   - Добавлен операторский комментарий и ручная смена статуса; уведомления (email/telegram) оставить на этап 2.

3. **Нет требований к безопасному хранилищу файлов.**
   - Для MVP локальное хранилище; для production рекомендован S3 + антивирус + signed URL.

4. **Нет аудита изменений в админке.**
   - Для MVP не реализован audit trail; добавить таблицу `admin_events` на следующем этапе.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Открыть: `http://localhost:5000`
