from datetime import datetime, timedelta
from decimal import Decimal
import secrets

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    can_edit_requisites = db.Column(db.Boolean, default=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship("Role")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role and self.role.code == "admin"

    @property
    def is_operator(self):
        return self.role and self.role.code == "operator"


class Country(db.Model):
    __tablename__ = "countries"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)


class City(db.Model):
    __tablename__ = "cities"
    id = db.Column(db.Integer, primary_key=True)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    country = db.relationship("Country")


class Court(db.Model):
    __tablename__ = "courts"
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    city = db.relationship("City")


class TimeSlot(db.Model):
    __tablename__ = "time_slots"
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(32), nullable=False, unique=True)
    start_at = db.Column(db.String(5), nullable=False)
    end_at = db.Column(db.String(5), nullable=False)


class Price(db.Model):
    __tablename__ = "prices"
    id = db.Column(db.Integer, primary_key=True)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=False)
    court_id = db.Column(db.Integer, db.ForeignKey("courts.id"), nullable=False)
    time_slot_id = db.Column(db.Integer, db.ForeignKey("time_slots.id"), nullable=False)
    event_type = db.Column(db.String(30), default="regular", nullable=False)
    day_of_week = db.Column(db.Integer, nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)

    country = db.relationship("Country")
    city = db.relationship("City")
    court = db.relationship("Court")
    time_slot = db.relationship("TimeSlot")


class PaymentMethod(db.Model):
    __tablename__ = "payment_methods"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)


class PaymentAccount(db.Model):
    __tablename__ = "payment_accounts"
    id = db.Column(db.Integer, primary_key=True)
    payment_method_id = db.Column(db.Integer, db.ForeignKey("payment_methods.id"), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    instruction = db.Column(db.Text, nullable=True)
    requisites = db.Column(db.Text, nullable=True)
    qr_image_path = db.Column(db.String(255), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    payment_method = db.relationship("PaymentMethod")


class CryptoAccount(db.Model):
    __tablename__ = "crypto_accounts"
    id = db.Column(db.Integer, primary_key=True)
    exchange = db.Column(db.String(20), nullable=False)
    account_id = db.Column(db.String(120), nullable=False)
    instruction = db.Column(db.Text, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)


class Tournament(db.Model):
    __tablename__ = "tournaments"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    fixed_amount = db.Column(db.Numeric(10, 2), nullable=False)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=True)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=True)
    event_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    country = db.relationship("Country")
    city = db.relationship("City")


class PaymentLink(db.Model):
    __tablename__ = "payment_links"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    link_type = db.Column(db.String(20), nullable=False, default="personal")
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=True)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=True)
    court_id = db.Column(db.Integer, db.ForeignKey("courts.id"), nullable=True)
    play_date = db.Column(db.Date, nullable=True)
    time_slot_id = db.Column(db.Integer, db.ForeignKey("time_slots.id"), nullable=True)
    fixed_amount = db.Column(db.Numeric(10, 2), nullable=False)
    event_type = db.Column(db.String(30), nullable=False, default="personal")
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournaments.id"), nullable=True)

    country = db.relationship("Country")
    city = db.relationship("City")
    court = db.relationship("Court")
    time_slot = db.relationship("TimeSlot")
    tournament = db.relationship("Tournament")


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    booking_type = db.Column(db.String(20), default="regular", nullable=False)

    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=True)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"), nullable=True)
    court_id = db.Column(db.Integer, db.ForeignKey("courts.id"), nullable=True)
    play_date = db.Column(db.Date, nullable=True)
    time_slot_id = db.Column(db.Integer, db.ForeignKey("time_slots.id"), nullable=True)

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method_id = db.Column(db.Integer, db.ForeignKey("payment_methods.id"), nullable=False)
    crypto_exchange = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(30), default="new", nullable=False)
    operator_comment = db.Column(db.Text, nullable=True)

    payment_link_id = db.Column(db.Integer, db.ForeignKey("payment_links.id"), nullable=True)

    country = db.relationship("Country")
    city = db.relationship("City")
    court = db.relationship("Court")
    time_slot = db.relationship("TimeSlot")
    payment_method = db.relationship("PaymentMethod")
    payment_link = db.relationship("PaymentLink")


class PaymentProof(db.Model):
    __tablename__ = "payment_proofs"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    booking = db.relationship("Booking")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def seed_defaults():
    if not Role.query.first():
        db.session.add_all([
            Role(code="admin", name="Administrator"),
            Role(code="operator", name="Operator"),
        ])
        db.session.commit()

    if not Country.query.first():
        thailand = Country(name="Thailand")
        db.session.add(thailand)
        db.session.flush()

        phuket = City(country_id=thailand.id, name="Phuket")
        db.session.add(phuket)
        db.session.flush()

        court = Court(city_id=phuket.id, name="Sharks Padel Court", address="Phuket, Bang Tao")
        db.session.add(court)
        db.session.flush()

        slots = [
            TimeSlot(label="08:00-09:00", start_at="08:00", end_at="09:00"),
            TimeSlot(label="18:00-19:00", start_at="18:00", end_at="19:00"),
        ]
        db.session.add_all(slots)
        db.session.flush()

        for slot in slots:
            db.session.add(Price(country_id=thailand.id, city_id=phuket.id, court_id=court.id, time_slot_id=slot.id, amount=Decimal("1200.00")))

        db.session.commit()

    if not PaymentMethod.query.first():
        methods = [
            PaymentMethod(code="sbp", name="СБП", is_active=True),
            PaymentMethod(code="thai_qr", name="Банковская карта / Thai QR", is_active=True),
            PaymentMethod(code="crypto", name="Крипта", is_active=True),
        ]
        db.session.add_all(methods)
        db.session.flush()

        for method in methods:
            if method.code != "crypto":
                db.session.add(PaymentAccount(
                    payment_method_id=method.id,
                    title=f"{method.name} реквизиты",
                    instruction="Оплатите точную сумму и нажмите 'Я оплатил'.",
                    requisites="Получатель: Sharks Padel\nБанк: Demo Bank\nНомер: 1234 5678",
                    comment="После оплаты загрузите чек.",
                ))

        db.session.add_all([
            CryptoAccount(exchange="Bybit", account_id="BYBIT_123456", instruction="Внутренний перевод без комиссии", comment="USDT TRC20"),
            CryptoAccount(exchange="HTX", account_id="HTX_987654", instruction="Внутренний перевод без комиссии", comment="USDT TRC20"),
        ])
        db.session.commit()

    if not User.query.filter_by(email="admin@padel.local").first():
        admin_role = Role.query.filter_by(code="admin").first()
        operator_role = Role.query.filter_by(code="operator").first()

        admin = User(email="admin@padel.local", role_id=admin_role.id, can_edit_requisites=True)
        admin.set_password("admin123")
        operator = User(email="operator@padel.local", role_id=operator_role.id, can_edit_requisites=False)
        operator.set_password("operator123")
        db.session.add_all([admin, operator])
        db.session.commit()

    if not Tournament.query.first():
        country = Country.query.first()
        city = City.query.first()
        tournament = Tournament(
            title="Sharks Weekly Cup",
            description="Еженедельный турнир для игроков уровня intermediate.",
            fixed_amount=Decimal("2500.00"),
            country_id=country.id if country else None,
            city_id=city.id if city else None,
            event_date=datetime.utcnow().date() + timedelta(days=14),
        )
        db.session.add(tournament)
        db.session.commit()
