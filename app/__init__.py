import os
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "admin_login"
csrf = CSRFProtect()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = _required_env("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///padel_mvp.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["PROOF_UPLOAD_FOLDER"] = os.getenv("PROOF_UPLOAD_FOLDER", os.path.join(app.instance_path, "proof_uploads"))
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

    os.makedirs(app.config["PROOF_UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models, routes  # noqa: F401
    from .cli import register_cli

    with app.app_context():
        db.create_all()
        models.seed_defaults()

    routes.init_routes(app)
    register_cli(app)
    return app
