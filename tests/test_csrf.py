"""CSRF protection is on for every POST (Flask-WTF CSRFProtect)."""
import re

import pytest

from garagesystem.models import Car, Task
from tests.factories import make_car

HTTPS = 'https://localhost'  # session cookies are Secure-only
# Over HTTPS, CSRFProtect also requires a same-site Referer, as browsers send.
SAME_SITE = {'Referer': f'{HTTPS}/board'}


@pytest.fixture
def csrf_client(app):
    app.config['WTF_CSRF_ENABLED'] = True
    return app.test_client()


def _token(client, url):
    html = client.get(url, base_url=HTTPS).get_data(as_text=True)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


def test_post_without_token_is_refused(csrf_client, db):
    car = make_car()
    db.session.commit()
    r = csrf_client.post(f'/cars/{car.id}/delete', base_url=HTTPS,
                         headers={'Referer': f'{HTTPS}/cars/{car.id}'})
    # Bounced back to the page with a message, and nothing deleted
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/cars/{car.id}')
    assert db.session.get(Car, car.id) is not None


def test_post_with_token_goes_through(csrf_client, db):
    car = make_car()
    db.session.commit()
    token = _token(csrf_client, f'/cars/{car.id}')
    csrf_client.post(f'/cars/{car.id}/delete', data={'csrf_token': token}, base_url=HTTPS, headers=SAME_SITE)
    assert db.session.get(Car, car.id) is None


def test_offsite_referrer_is_not_followed(csrf_client, db):
    r = csrf_client.post('/settings', base_url=HTTPS, headers={'Referer': 'https://evil.example/x'})
    assert r.status_code == 302 and 'evil.example' not in r.headers['Location']


def test_header_token_is_accepted(csrf_client, db):
    """fetch()-style requests can send the token as an X-CSRFToken header."""
    task = Task(title='A', status='todo')
    db.session.add(task)
    db.session.commit()

    r = csrf_client.post(f'/board/tasks/{task.id}/done', base_url=HTTPS, headers=SAME_SITE)
    assert db.session.get(Task, task.id).status == 'todo'

    token = _token(csrf_client, '/board')
    csrf_client.post(f'/board/tasks/{task.id}/done', base_url=HTTPS,
                     headers={**SAME_SITE, 'X-CSRFToken': token})
    assert db.session.get(Task, task.id).status == 'done'


def test_token_from_another_site_is_refused(csrf_client, db):
    """A valid token is still refused if the request came from another site."""
    car = make_car()
    db.session.commit()
    token = _token(csrf_client, f'/cars/{car.id}')
    csrf_client.post(f'/cars/{car.id}/delete', data={'csrf_token': token}, base_url=HTTPS,
                     headers={'Referer': 'https://evil.example/'})
    assert db.session.get(Car, car.id) is not None
