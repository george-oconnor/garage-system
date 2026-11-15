import re
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_session import Session
from sqlalchemy import MetaData
from werkzeug.middleware.proxy_fix import ProxyFix
import sentry_sdk

metadata = MetaData(naming_convention={
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
})

flask_session = Session()
db = SQLAlchemy(metadata=metadata)
migrate = Migrate()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'users.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'


def create_app():
    from garagesystem.config import Config, DEV_SECRET_KEY

    app = Flask(__name__)
    app.config.from_object(Config)

    if app.config['SECRET_KEY'] == DEV_SECRET_KEY and app.config['SYSTEM'] != 'DEVELOPMENT':
        raise RuntimeError(
            f"SECRET_KEY is the public development default but SYSTEM is {app.config['SYSTEM']!r}. "
            "Set SECRET_KEY in instance/config.json."
        )

    # Behind nginx -> trust one proxy hop for X-Forwarded-{Proto,For,Host}
    # so request.is_secure/url_for(_external=True) reflect the real client.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PREFERRED_URL_SCHEME'] = 'https'

    if app.config.get('SENTRY_DSN'):
        sentry_sdk.init(
            dsn=app.config['SENTRY_DSN'],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            environment=app.config.get('SENTRY_ENVIRONMENT', 'production'),
        )

    try:
        from redis import Redis
        import rq
        app.redis = Redis.from_url(app.config['REDIS_URL'])
        app.task_queue = rq.Queue('garagesystem-tasks', connection=app.redis)
    except Exception:
        app.redis = None
        app.task_queue = None

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    flask_session.init_app(app)

    @app.template_filter('format_reg')
    def format_reg(reg):
        """Format Irish vehicle registration with dashes: 241D12345 -> 241-D-12345."""
        if not reg:
            return reg
        reg = reg.strip().upper()
        if '-' in reg:
            return reg
        m = re.match(r'^(\d{2,3})([A-Z]{1,3})(\d{1,6})$', reg)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return reg

    @app.context_processor
    def inject_globals():
        from datetime import datetime
        from flask_wtf.csrf import generate_csrf
        return {
            'now': datetime.utcnow(),
            'app_name': app.config.get('APP_NAME', 'Garage System'),
            'csrf_token': generate_csrf,
        }

    from garagesystem.main.routes import main
    from garagesystem.cars.routes import cars
    from garagesystem.events.routes import events
    from garagesystem.users.routes import users
    from garagesystem.errors.handlers import errors

    app.register_blueprint(main)
    app.register_blueprint(cars)
    app.register_blueprint(events)
    app.register_blueprint(users)
    app.register_blueprint(errors)

    return app
