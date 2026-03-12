import click
from flask.cli import with_appcontext

from . import db
from .models import Role, User


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @with_appcontext
    def create_admin(email, password):
        email = email.strip().lower()
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("User already exists.")

        admin_role = Role.query.filter_by(code="admin").first()
        if not admin_role:
            raise click.ClickException("Admin role not found.")

        user = User(email=email, role_id=admin_role.id, can_edit_requisites=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Admin created successfully.")
