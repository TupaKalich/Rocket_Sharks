import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from . import db
from .models import (
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
    TimeSlot,
    Tournament,
    User,
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}


def init_routes(app):
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
        play_date = request.form.get("play_date")

        if not all([country_id, city_id, court_id, time_slot_id, play_date]):
            flash("Заполните страну, город, корт, дату и время.", "error")
            return redirect(url_for("home"))

        price = Price.query.filter_by(
            country_id=country_id,
            city_id=city_id,
            court_id=court_id,
            time_slot_id=time_slot_id,
        ).first()
        if not price:
            flash("Цена для выбранных параметров не задана.", "error")
            return redirect(url_for("home"))

        session["booking_draft"] = {
            "booking_type": "regular",
            "country_id": country_id,
            "city_id": city_id,
            "court_id": court_id,
            "play_date": play_date,
            "time_slot_id": time_slot_id,
            "amount": str(price.amount),
            "payment_link_id": None,
        }
        return redirect(url_for("payment"))

    @app.route("/pay")
    def payment():
        draft = session.get("booking_draft")
        if not draft or Decimal(draft.get("amount", "0")) <= 0:
            flash("Сначала выберите параметры игры.", "error")
            return redirect(url_for("home"))

        methods = PaymentMethod.query.filter_by(is_active=True).all()
        return render_template("public/payment.html", draft=draft, methods=methods)

    @app.post("/pay/select")
    def payment_select():
        draft = session.get("booking_draft")
        if not draft:
            flash("Сессия истекла. Повторите выбор.", "error")
            return redirect(url_for("home"))

        method_id = request.form.get("payment_method_id", type=int)
        crypto_exchange = request.form.get("crypto_exchange")
        method = PaymentMethod.query.get_or_404(method_id)

        if method.code == "crypto" and crypto_exchange not in ["Bybit", "HTX"]:
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

        return redirect(url_for("upload_proof"))

    @app.route("/proof")
    def upload_proof():
        draft = session.get("booking_draft")
        if not draft or not draft.get("payment_method_id"):
            flash("Сначала выберите способ оплаты.", "error")
            return redirect(url_for("payment"))

        method = PaymentMethod.query.get(draft["payment_method_id"])
        account = None
        if session.get("payment_account_type") == "crypto":
            account = CryptoAccount.query.get(session.get("payment_account_id"))
        else:
            account = PaymentAccount.query.get(session.get("payment_account_id"))

        return render_template("public/proof.html", draft=draft, method=method, account=account)

    def is_allowed(filename):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

    @app.post("/proof")
    def create_booking_from_proof():
        draft = session.get("booking_draft")
        if not draft:
            flash("Сессия истекла. Повторите оформление.", "error")
            return redirect(url_for("home"))

        file = request.files.get("payment_proof")
        if not file or file.filename == "":
            flash("Загрузите чек.", "error")
            return redirect(url_for("upload_proof"))

        if not is_allowed(file.filename):
            flash("Допустимые форматы: JPG, PNG, PDF.", "error")
            return redirect(url_for("upload_proof"))

        unique = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], unique)
        file.save(path)

        booking = Booking(
            booking_type=draft["booking_type"],
            country_id=draft.get("country_id"),
            city_id=draft.get("city_id"),
            court_id=draft.get("court_id"),
            play_date=datetime.strptime(draft["play_date"], "%Y-%m-%d").date() if draft.get("play_date") else None,
            time_slot_id=draft.get("time_slot_id"),
            amount=Decimal(draft["amount"]),
            payment_method_id=draft["payment_method_id"],
            crypto_exchange=draft.get("crypto_exchange"),
            status="pending_confirmation",
            payment_link_id=draft.get("payment_link_id"),
        )
        db.session.add(booking)
        db.session.flush()

        proof = PaymentProof(booking_id=booking.id, file_path=f"uploads/{unique}")
        db.session.add(proof)
        db.session.commit()

        session.pop("booking_draft", None)
        session.pop("payment_account_type", None)
        session.pop("payment_account_id", None)

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

        if link.link_type == "tournament" and link.tournament:
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
        email = request.form.get("email")
        password = request.form.get("password")
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

    def ensure_staff():
        if not current_user.is_authenticated or not (current_user.is_admin or current_user.is_operator):
            abort(403)

    def ensure_admin():
        ensure_staff()
        if not current_user.is_admin:
            abort(403)

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
        return render_template("admin/booking_card.html", booking=booking, proof=proof)

    @app.post("/admin/bookings/<int:booking_id>/status")
    @login_required
    def admin_booking_status(booking_id):
        ensure_staff()
        booking = Booking.query.get_or_404(booking_id)
        booking.status = request.form.get("status")
        booking.operator_comment = request.form.get("operator_comment")
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
        account.title = request.form.get("title")
        account.instruction = request.form.get("instruction")
        account.requisites = request.form.get("requisites")
        account.comment = request.form.get("comment")
        account.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        return redirect(url_for("admin_requisites"))

    @app.post("/admin/crypto/<int:account_id>")
    @login_required
    def admin_crypto_update(account_id):
        ensure_staff()
        if current_user.is_operator and not current_user.can_edit_requisites:
            abort(403)

        account = CryptoAccount.query.get_or_404(account_id)
        account.account_id = request.form.get("account_id")
        account.instruction = request.form.get("instruction")
        account.comment = request.form.get("comment")
        account.is_active = bool(request.form.get("is_active"))
        db.session.commit()
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
        )

    @app.post("/admin/links")
    @login_required
    def admin_links_create():
        ensure_staff()
        link_type = request.form.get("link_type")
        expires_days = request.form.get("expires_days", type=int) or 7
        expires_at = datetime.utcnow() + timedelta(days=expires_days)

        link = PaymentLink(
            link_type=link_type,
            fixed_amount=Decimal(request.form.get("fixed_amount")),
            country_id=request.form.get("country_id", type=int),
            city_id=request.form.get("city_id", type=int),
            court_id=request.form.get("court_id", type=int),
            time_slot_id=request.form.get("time_slot_id", type=int),
            play_date=datetime.strptime(request.form.get("play_date"), "%Y-%m-%d").date() if request.form.get("play_date") else None,
            tournament_id=request.form.get("tournament_id", type=int),
            event_type=link_type,
            expires_at=expires_at,
            is_active=True,
        )
        db.session.add(link)
        db.session.commit()
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
        db.session.add(Country(name=request.form.get("name")))
        db.session.commit()
        return redirect(url_for("admin_geo"))

    @app.post("/admin/geo/city")
    @login_required
    def add_city():
        ensure_admin()
        db.session.add(City(name=request.form.get("name"), country_id=request.form.get("country_id", type=int)))
        db.session.commit()
        return redirect(url_for("admin_geo"))

    @app.post("/admin/geo/court")
    @login_required
    def add_court():
        ensure_admin()
        db.session.add(Court(name=request.form.get("name"), address=request.form.get("address"), city_id=request.form.get("city_id", type=int)))
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
        p = Price(
            country_id=request.form.get("country_id", type=int),
            city_id=request.form.get("city_id", type=int),
            court_id=request.form.get("court_id", type=int),
            time_slot_id=request.form.get("time_slot_id", type=int),
            amount=Decimal(request.form.get("amount")),
            event_type=request.form.get("event_type") or "regular",
        )
        db.session.add(p)
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
        user = User(
            email=request.form.get("email"),
            role_id=1 if request.form.get("role") == "admin" else 2,
            can_edit_requisites=bool(request.form.get("can_edit_requisites")),
        )
        user.set_password(request.form.get("password"))
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("admin_users"))

