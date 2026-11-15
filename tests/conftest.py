import os
import tempfile

# Must be set before the app (and its Config) is imported.
os.environ['DATABASE_URL'] = 'sqlite://'

import pytest

from garagesystem import create_app, db as _db


@pytest.fixture
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        LOGIN_DISABLED=True,
        SESSION_FILE_DIR=tempfile.mkdtemp(),
    )
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()
