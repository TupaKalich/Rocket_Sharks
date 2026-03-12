import imghdr
import os
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from . import db
from .constants import (
    ALLOWED_STATUS_TRANSITIONS,
    ALLOWED_UPLOAD_EXTENSIONS,
    BOOKING_STATUSES,
    CRYPTO_EXCHANGES,
    IDEMPOTENCY_SESSION_KEY,
    PAYMENT_LINK_TYPES,
)
from .models import (
    AuditLog,
    Booking,
    City,
    Country,
    Court,
    CryptoAccount,
    PaymentAccount,
    PaymentLink,
    PaymentMethod,
    PaymentProof,
    Price,
    Role,
    TimeSlot,
    Tournament,
    User,
    serialize_model_state,
)


def init_routes(app):
    def is_allowed_extension(filename):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS

    def is_valid_upload_signature(file_storage):
        file_storage.stream.seek(0)
        header = file_storage.stream.read(16)
        file_storage.stream.seek(0)

        if header.startswith(b"%PDF-"):
            return True

        image_kind = imghdr.what(None, h=header)
        return image_kind in {"jpeg", "png"}

    def safe_decimal(raw_value):
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value

    def safe_parse_date(raw_date):
        if not raw_date:
            return None
        try:
            return datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            return None

    def validate_geo(country_id, city_id, court_id, time_slot_id):
        country = Country.query.get(country_id) if country_id else None
        city = City.query.get(city_id) if city_id else None
        court = Court.query.get(court_id) if court_id else None
        slot = TimeSlot.query.get(time_slot_id) if time_slot_id else None

        if country_id and not country:
            return False
        if city_id and not city:
            return False
        if court_id and not court:
            return False
        if time_slot_id and not slot:
            return False

        if city and country and city.country_id != country.id:
            return False
        if court and city and court.city_id != city.id:
            return False
        return True

    def ensure_staff():
        if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_operator):
            abort(403)

    def ensure_admin():
        ensure_staff()
        if not current_user.is_admin:
            abort(403)

    def log_admin_action(action, entity_type, entity_id, before=None, after=None):
        if not current_user.is_authenticated:
            return
        db.session.add(
            AuditLog(
                actor_user_id=current_user.id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                before_json=before,
                after_json=after,
            )
        )

    @app.route("/")
    def home():
        countries = Country.query.order_by(Country.name).all()
        cities = City.query.order_by(City.name).all()
        courts = Court.query.order_by(Court.name).all()
        slots = TimeSlot.query.order_by(TimeSlot.start_at).all()
        return render_template("public/home.html", countries=countries, cities=cities, courts=courts, slots=slots)

    @app.post("/calculate")
    def calculate_price():
        country_id = request.form.get("country_id", type=int)
        city_id = request.form.get("city_id", type=int)
        court_id = request.form.get("court_id", type=int)
        time_slot_id = request.form.get("time_slot_id", type=int)
        play_date_raw = request.form.get("play_date")
        play_date = safe_parse_date(play_date_raw)

        if not all([country_id, city_id, court_id, time_slot_id, play_date]):
            flash("Заполните страну, город, корт, дату и время корректно.", "error")
            return redirect(url_for("home"))

        if not validate_geo(country_id, city_id, court_id, time_slot_id):
            flash("Некорректная комбинация страны, города, корта или слота.", "error")
            return redirect(url_for("home"))

        price = Price.query.filter_by(
            country_id=country_id,
            city_id=city_id,
            court_id=court_id,
            time_slot_id=time_slot_id,
            event_type="regular",
        ).first()
        if not price:
            flash("Цена для выбранных параметров не задана.", "error")
            return redirect(url_for("home"))

        session["booking_draft"] = {
            "booking_type": "regular",
            "country_id": country_id,
            "city_id": city_id,
            "court_id": court_id,
            "play_date": play_date.isoformat(),
            "time_slot_id": time_slot_id,
            "amount": str(price.amount),
            "payment_link_id": None,
        }
        return redirect(url_for("payment"))

    @app.route("/pay")
    def payment():
        draft = session.get("booking_draft")
        if not draft or safe_decimal(draft.get("amount")) is None:
            flash("Сначала выберите параметры игры.", "error")
            return redirect(url_for("home"))

        methods = PaymentMethod.query.filter_by(is_active=True).all()
        return render_template("public/payment.html", draft=draft, methods=methods, exchanges=CRYPTO_EXCHANGES)

    @app.post("/pay/select")
    def payment_select():
        draft = session.get("booking_draft")
        if not draft:
            flash("Сессия истекла. Повторите выбор.", "error")
            return redirect(url_for("home"))

        method_id = request.form.get("payment_method_id", type=int)
        if not method_id:
            flash("Выберите способ оплаты.", "error")
            return redirect(url_for("payment"))

        method = PaymentMethod.query.get(method_id)
        if not method or not method.is_active:
            flash("Способ оплаты недоступен.", "error")
            return redirect(url_for("payment"))

        crypto_exchange = request.form.get("crypto_exchange")
        if method.code == "crypto" and crypto_exchange not in CRYPTO_EXCHANGES:
            flash("Для крипты нужно выбрать биржу.", "error")
            return redirect(url_for("payment"))

        draft["payment_method_id"] = method.id
        draft["crypto_exchange"] = crypto_exchange if method.code == "crypto" else None
        session["booking_draft"] = draft

        if method.code == "crypto":
            account = CryptoAccount.query.filter_by(exchange=crypto_exchange, is_active=True).first()
            if not account:
                flash("Реквизиты по выбранной бирже недоступны.", "error")
                return redirect(url_for("payment"))
            session["payment_account_type"] = "crypto"
            session["payment_account_id"] = account.id
        else:
            account = PaymentAccount.query.filter_by(payment_method_id=method.id, is_active=True).first()
            if not account:
                flash("Реквизиты временно недоступны.", "error")
                return redirect(url_for("payment"))
            session["payment_account_type"] = "default"
            session["payment_account_id"] = account.id

        session[IDEMPOTENCY_SESSION_KEY] = secrets.token_urlsafe(24)
        return redirect(url_for("upload_proof"))

    @app.route("/proof")
    def upload_proof():
        draft = session.get("booking_draft")
        if not draft or not draft.get("payment_method_id"):
            flash("Сначала выберите способ оплаты.", "error")
            return redirect(url_for("payment"))

        method = PaymentMethod.query.get(draft["payment_method_id"])
        if not method:
            flash("Способ оплаты недоступен.", "error")
            return redirect(url_for("payment"))

        if session.get("payment_account_type") == "crypto":
            account = CryptoAccount.query.get(session.get("payment_account_id"))
        else:
            account = PaymentAccount.query.get(session.get("payment_account_id"))

        if not account:
            flash("Реквизиты не найдены.", "error")
            return redirect(url_for("payment"))

        token = session.get(IDEMPOTENCY_SESSION_KEY)
        if not token:
            token = secrets.token_urlsafe(24)
            session[IDEMPOTENCY_SESSION_KEY] = token

        return render_template("public/proof.html", draft=draft, method=method, account=account, form_token=token)

    @app.post("/proof")
    def create_booking_from_proof():
        draft = session.get("booking_draft")
        if not draft:
            flash("Сессия истекла. Повторите оформление.", "error")
            return redirect(url_for("home"))

        form_token = request.form.get("form_token")
        session_token = session.get(IDEMPOTENCY_SESSION_KEY)
        if not form_token or not session_token or form_token != session_token:
            flash("Форма уже была отправлена или сессия устарела.", "error")
            return redirect(url_for("upload_proof"))

        amount = safe_decimal(draft.get("amount"))
        play_date = safe_parse_date(draft.get("play_date")) if draft.get("play_date") else None
        if amount is None:
            flash("Сумма заявки некорректна.", "error")
            return redirect(url_for("home"))

        if draft.get("booking_type") in {"regular", "personal_link"}:
            if not all([draft.get("country_id"), draft.get("city_id"), draft.get("court_id"), draft.get("time_slot_id"), play_date]):
                flash("Для заявки не хватает обязательных параметров игры.", "error")
                return redirect(url_for("home"))
            if not validate_geo(draft.get("country_id"), draft.get("city_id"), draft.get("court_id"), draft.get("time_slot_id")):
                flash("Некорректные параметры игры.", "error")
                return redirect(url_for("home"))

        file = request.files.get("payment_proof")
        if not file or file.filename == "":
            flash("Загрузите чек.", "error")
            return redirect(url_for("upload_proof"))

        if not is_allowed_extension(file.filename) or not is_valid_upload_signature(file):
            flash("Допустимые форматы: JPG, PNG, PDF.", "error")
            return redirect(url_for("upload_proof"))

        unique = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        path = os.path.join(app.config["PROOF_UPLOAD_FOLDER"], unique)
        file.save(path)

        payment_method = PaymentMethod.query.get(draft.get("payment_method_id"))
        if not payment_method:
            flash("Метод оплаты не найден.", "error")
            return redirect(url_for("payment"))

        booking = Booking(
            booking_type=draft["booking_type"],
            country_id=draft.get("country_id"),
            city_id=draft.get("city_id"),
            court_id=draft.get("court_id"),
            play_date=play_date,
            time_slot_id=draft.get("time_slot_id"),
            amount=amount,
            payment_method_id=payment_method.id,
            crypto_exchange=draft.get("crypto_exchange"),
            status="pending_confirmation",
            payment_link_id=draft.get("payment_link_id"),
        )
        db.session.add(booking)
        db.session.flush()

        proof = PaymentProof(booking_id=booking.id, file_path=unique)
        db.session.add(proof)
        db.session.commit()

        session.pop("booking_draft", None)
        session.pop("payment_account_type", None)
        session.pop("payment_account_id", None)
        session.pop(IDEMPOTENCY_SESSION_KEY, None)

        return redirect(url_for("success", booking_id=booking.id))

    @app.route("/success/<int:booking_id>")
    def success(booking_id):
        booking = Booking.query.get_or_404(booking_id)
        return render_template("public/success.html", booking=booking)

    @app.route("/l/<token>")
    def payment_by_link(token):
        link = PaymentLink.query.filter_by(token=token).first_or_404()
        if not link.is_active or (link.expires_at and link.expires_at < datetime.utcnow()):
            abort(410, "Ссылка недействительна")

        if link.link_type == "tournament":
            if not link.tournament:
                abort(404)
            session["booking_draft"] = {
                "booking_type": "tournament",
                "country_id": link.country_id,
                "city_id": link.city_id,
                "court_id": link.court_id,
                "play_date": link.play_date.isoformat() if link.play_date else None,
                "time_slot_id": link.time_slot_id,
                "amount": str(link.fixed_amount),
                "payment_link_id": link.id,
            }
            return render_template("public/tournament_link.html", link=link)

        session["booking_draft"] = {
            "booking_type": "personal_link",
            "country_id": link.country_id,
            "city_id": link.city_id,
            "court_id": link.court_id,
            "play_date": link.play_date.isoformat() if link.play_date else None,
            "time_slot_id": link.time_slot_id,
            "amount": str(link.fixed_amount),
            "payment_link_id": link.id,
        }
        return render_template("public/personal_link.html", link=link)

    @app.get("/admin/login")
    def admin_login():
        return render_template("admin/login.html")

    @app.post("/admin/login")
    def admin_login_post():
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email, is_active=True).first()

        if not user or not user.check_password(password):
            flash("Неверный логин или пароль", "error")
            return redirect(url_for("admin_login"))

        login_user(user)
        return redirect(url_for("admin_dashboard"))

    @app.get("/admin/logout")
    @login_required
    def admin_logout():
        logout_user()
        return redirect(url_for("admin_login"))

    @app.get("/admin/proofs/<int:proof_id>")
    @login_required
    def admin_proof_download(proof_id):
        ensure_staff()
        proof = PaymentProof.query.get_or_404(proof_id)
        path = os.path.join(app.config["PROOF_UPLOAD_FOLDER"], proof.file_path)
        if not os.path.exists(path):
            abort(404)
        return send_file(path, as_attachment=False)

    @app.get("/admin")
    @login_required
    def admin_dashboard():
        ensure_staff()
        counts = {
            "new": Booking.query.filter_by(status="new").count(),
            "pending": Booking.query.filter_by(status="pending_confirmation").count(),
            "confirmed": Booking.query.filter_by(status="confirmed").count(),
            "rejected": Booking.query.filter_by(status="rejected").count(),
        }
        return render_template("admin/dashboard.html", counts=counts)

    @app.get("/admin/bookings")
    @login_required
    def admin_bookings():
        ensure_staff()
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
        proof_map = {p.booking_id: p for p in PaymentProof.query.all()}
        return render_template("admin/bookings.html", bookings=bookings, proof_map=proof_map)

    @app.get("/admin/bookings/<int:booking_id>")
    @login_required
    def admin_booking_card(booking_id):
        ensure_staff()
        booking = Booking.query.get_or_404(booking_id)
        proof = PaymentProof.query.filter_by(booking_id=booking.id).first()
        return render_template("admin/booking_card.html", booking=booking, proof=proof, booking_statuses=BOOKING_STATUSES)

    @app.post("/admin/bookings/<int:booking_id>/status")
    @login_required
    def admin_booking_status(booking_id):
        ensure_staff()
        booking = Booking.query.get_or_404(booking_id)

        next_status = request.form.get("status")
        comment = request.form.get("operator_comment")
        if next_status not in BOOKING_STATUSES:
            flash("Недопустимый статус.", "error")
            return redirect(url_for("admin_booking_card", booking_id=booking.id))

        allowed_next = ALLOWED_STATUS_TRANSITIONS.get(booking.status, set())
        if next_status != booking.status and next_status not in allowed_next:
            flash("Недопустимый переход статуса.", "error")
            return redirect(url_for("admin_booking_card", booking_id=booking.id))

        before = serialize_model_state(booking, ["status", "operator_comment"])
        booking.status = next_status
        booking.operator_comment = comment
        after = serialize_model_state(booking, ["status", "operator_comment"])
        log_admin_action("booking_status_update", "booking", booking.id, before=before, after=after)
        db.session.commit()
        flash("Статус обновлен", "ok")
        return redirect(url_for("admin_booking_card", booking_id=booking.id))

    @app.get("/admin/requisites")
    @login_required
    def admin_requisites():
        ensure_staff()
        if current_user.is_operator and not current_user.can_edit_requisites:
            abort(403)

        accounts = PaymentAccount.query.all()
        crypto = CryptoAccount.query.all()
        return render_template("admin/requisites.html", accounts=accounts, crypto=crypto)

    @app.post("/admin/requisites/<int:account_id>")
    @login_required
    def admin_requisites_update(account_id):
        ensure_staff()
        if current_user.is_operator and not current_user.can_edit_requisites:
            abort(403)

        account = PaymentAccount.query.get_or_404(account_id)
        title = (request.form.get("title") or "").strip()
        requisites = (request.form.get("requisites") or "").strip()

        if not title or not requisites:
            flash("Название и реквизиты обязательны.", "error")
            return redirect(url_for("admin_requisites"))

        before = serialize_model_state(account, ["title", "instruction", "requisites", "comment", "is_active"])
        account.title = title
        account.instruction = (request.form.get("instruction") or "").strip() or None
        account.requisites = requisites
        account.comment = (request.form.get("comment") or "").strip() or None
        account.is_active = bool(request.form.get("is_active"))
        after = serialize_model_state(account, ["title", "instruction", "requisites", "comment", "is_active"])
        log_admin_action("payment_account_update", "payment_account", account.id, before=before, after=after)
        db.session.commit()
        flash("Реквизиты обновлены.", "ok")
        return redirect(url_for("admin_requisites"))

    @app.post("/admin/crypto/<int:account_id>")
    @login_required
    def admin_crypto_update(account_id):
        ensure_staff()
        if current_user.is_operator and not current_user.can_edit_requisites:
            abort(403)

        account = CryptoAccount.query.get_or_404(account_id)
        account_id_value = (request.form.get("account_id") or "").strip()
        if not account_id_value:
            flash("ID аккаунта биржи обязателен.", "error")
            return redirect(url_for("admin_requisites"))

        before = serialize_model_state(account, ["account_id", "instruction", "comment", "is_active"])
        account.account_id = account_id_value
        account.instruction = (request.form.get("instruction") or "").strip() or None
        account.comment = (request.form.get("comment") or "").strip() or None
        account.is_active = bool(request.form.get("is_active"))
        after = serialize_model_state(account, ["account_id", "instruction", "comment", "is_active"])
        log_admin_action("crypto_account_update", "crypto_account", account.id, before=before, after=after)
        db.session.commit()
        flash("Крипто-реквизиты обновлены.", "ok")
        return redirect(url_for("admin_requisites"))

    @app.get("/admin/links")
    @login_required
    def admin_links():
        ensure_staff()
        links = PaymentLink.query.order_by(PaymentLink.id.desc()).all()
        countries = Country.query.all()
        cities = City.query.all()
        courts = Court.query.all()
        slots = TimeSlot.query.all()
        tournaments = Tournament.query.filter_by(is_active=True).all()
        return render_template(
            "admin/links.html",
            links=links,
            countries=countries,
            cities=cities,
            courts=courts,
            slots=slots,
            tournaments=tournaments,
            link_types=PAYMENT_LINK_TYPES,
        )

    @app.post("/admin/links")
    @login_required
    def admin_links_create():
        ensure_staff()
        link_type = request.form.get("link_type")
        if link_type not in PAYMENT_LINK_TYPES:
            flash("Недопустимый тип ссылки.", "error")
            return redirect(url_for("admin_links"))

        fixed_amount = safe_decimal(request.form.get("fixed_amount"))
        if fixed_amount is None:
            flash("Сумма должна быть больше 0.", "error")
            return redirect(url_for("admin_links"))

        expires_days = request.form.get("expires_days", type=int)
        if expires_days is None or expires_days < 1 or expires_days > 365:
            flash("Срок действия ссылки должен быть от 1 до 365 дней.", "error")
            return redirect(url_for("admin_links"))

        country_id = request.form.get("country_id", type=int)
        city_id = request.form.get("city_id", type=int)
        court_id = request.form.get("court_id", type=int)
        time_slot_id = request.form.get("time_slot_id", type=int)
        play_date = safe_parse_date(request.form.get("play_date")) if request.form.get("play_date") else None
        tournament_id = request.form.get("tournament_id", type=int)

        if link_type == "personal":
            if not all([country_id, city_id, court_id, time_slot_id, play_date]):
                flash("Для персональной ссылки обязательны страна, город, корт, дата и слот.", "error")
                return redirect(url_for("admin_links"))
            if not validate_geo(country_id, city_id, court_id, time_slot_id):
                flash("Некорректная география для персональной ссылки.", "error")
                return redirect(url_for("admin_links"))
            tournament_id = None

        if link_type == "tournament":
            if not tournament_id:
                flash("Для турнирной ссылки укажите турнир.", "error")
                return redirect(url_for("admin_links"))
            tournament = Tournament.query.get(tournament_id)
            if not tournament or not tournament.is_active:
                flash("Турнир не найден или неактивен.", "error")
                return redirect(url_for("admin_links"))
            if country_id or city_id or court_id or time_slot_id:
                if not validate_geo(country_id, city_id, court_id, time_slot_id):
                    flash("Некорректная география для турнирной ссылки.", "error")
                    return redirect(url_for("admin_links"))

        expires_at = datetime.utcnow() + timedelta(days=expires_days)
        link = PaymentLink(
            link_type=link_type,
            fixed_amount=fixed_amount,
            country_id=country_id,
            city_id=city_id,
            court_id=court_id,
            time_slot_id=time_slot_id,
            play_date=play_date,
            tournament_id=tournament_id,
            event_type=link_type,
            expires_at=expires_at,
            is_active=True,
        )
        db.session.add(link)
        db.session.flush()
        log_admin_action("payment_link_create", "payment_link", link.id, after=serialize_model_state(link, ["link_type", "fixed_amount", "is_active", "expires_at"]))
        db.session.commit()
        flash("Ссылка создана.", "ok")
        return redirect(url_for("admin_links"))

    @app.get("/admin/geo")
    @login_required
    def admin_geo():
        ensure_admin()
        countries = Country.query.all()
        cities = City.query.all()
        courts = Court.query.all()
        return render_template("admin/geo.html", countries=countries, cities=cities, courts=courts)

    @app.post("/admin/geo/country")
    @login_required
    def add_country():
        ensure_admin()
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Название страны обязательно.", "error")
            return redirect(url_for("admin_geo"))
        if Country.query.filter_by(name=name).first():
            flash("Такая страна уже существует.", "error")
            return redirect(url_for("admin_geo"))

        country = Country(name=name)
        db.session.add(country)
        db.session.flush()
        log_admin_action("country_create", "country", country.id, after=serialize_model_state(country, ["name"]))
        db.session.commit()
        return redirect(url_for("admin_geo"))

    @app.post("/admin/geo/city")
    @login_required
    def add_city():
        ensure_admin()
        name = (request.form.get("name") or "").strip()
        country_id = request.form.get("country_id", type=int)
        if not name or not country_id:
            flash("Город и страна обязательны.", "error")
            return redirect(url_for("admin_geo"))
        country = Country.query.get(country_id)
        if not country:
            flash("Страна не найдена.", "error")
            return redirect(url_for("admin_geo"))

        city = City(name=name, country_id=country_id)
        db.session.add(city)
        db.session.flush()
        log_admin_action("city_create", "city", city.id, after=serialize_model_state(city, ["name", "country_id"]))
        db.session.commit()
        return redirect(url_for("admin_geo"))

    @app.post("/admin/geo/court")
    @login_required
    def add_court():
        ensure_admin()
        name = (request.form.get("name") or "").strip()
        address = (request.form.get("address") or "").strip() or None
        city_id = request.form.get("city_id", type=int)
        if not name or not city_id:
            flash("Корт и город обязательны.", "error")
            return redirect(url_for("admin_geo"))
        city = City.query.get(city_id)
        if not city:
            flash("Город не найден.", "error")
            return redirect(url_for("admin_geo"))

        court = Court(name=name, address=address, city_id=city_id)
        db.session.add(court)
        db.session.flush()
        log_admin_action("court_create", "court", court.id, after=serialize_model_state(court, ["name", "city_id", "address"]))
        db.session.commit()
        return redirect(url_for("admin_geo"))

    @app.get("/admin/prices")
    @login_required
    def admin_prices():
        ensure_admin()
        prices = Price.query.all()
        countries = Country.query.all()
        cities = City.query.all()
        courts = Court.query.all()
        slots = TimeSlot.query.all()
        return render_template("admin/prices.html", prices=prices, countries=countries, cities=cities, courts=courts, slots=slots)

    @app.post("/admin/prices")
    @login_required
    def add_price():
        ensure_admin()
        country_id = request.form.get("country_id", type=int)
        city_id = request.form.get("city_id", type=int)
        court_id = request.form.get("court_id", type=int)
        time_slot_id = request.form.get("time_slot_id", type=int)
        amount = safe_decimal(request.form.get("amount"))
        event_type = (request.form.get("event_type") or "regular").strip()

        if not all([country_id, city_id, court_id, time_slot_id]) or amount is None:
            flash("Заполните параметры цены корректно.", "error")
            return redirect(url_for("admin_prices"))

        if not validate_geo(country_id, city_id, court_id, time_slot_id):
            flash("Некорректная связка страны/города/корта/слота.", "error")
            return redirect(url_for("admin_prices"))

        existing = Price.query.filter_by(
            country_id=country_id,
            city_id=city_id,
            court_id=court_id,
            time_slot_id=time_slot_id,
            event_type=event_type,
            day_of_week=None,
        ).first()

        if existing:
            before = serialize_model_state(existing, ["amount", "event_type"])
            existing.amount = amount
            after = serialize_model_state(existing, ["amount", "event_type"])
            log_admin_action("price_update", "price", existing.id, before=before, after=after)
        else:
            p = Price(
                country_id=country_id,
                city_id=city_id,
                court_id=court_id,
                time_slot_id=time_slot_id,
                amount=amount,
                event_type=event_type,
            )
            db.session.add(p)
            db.session.flush()
            log_admin_action("price_create", "price", p.id, after=serialize_model_state(p, ["country_id", "city_id", "court_id", "time_slot_id", "amount", "event_type"]))

        db.session.commit()
        return redirect(url_for("admin_prices"))

    @app.get("/admin/users")
    @login_required
    def admin_users():
        ensure_admin()
        users = User.query.all()
        return render_template("admin/users.html", users=users)

    @app.post("/admin/users")
    @login_required
    def admin_users_add():
        ensure_admin()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role_code = request.form.get("role")

        if not email or len(password) < 8:
            flash("Укажите email и пароль не короче 8 символов.", "error")
            return redirect(url_for("admin_users"))
        if User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже существует.", "error")
            return redirect(url_for("admin_users"))

        role = Role.query.filter_by(code=role_code).first()
        if not role:
            flash("Роль не найдена.", "error")
            return redirect(url_for("admin_users"))

        user = User(
            email=email,
            role_id=role.id,
            can_edit_requisites=bool(request.form.get("can_edit_requisites")),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        log_admin_action("user_create", "user", user.id, after=serialize_model_state(user, ["email", "role_id", "can_edit_requisites", "is_active"]))
        db.session.commit()
        return redirect(url_for("admin_users"))
