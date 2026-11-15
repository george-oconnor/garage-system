from flask import abort, current_app, request
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError


def check_post_csrf():
    """before_request hook for blueprints whose POSTs aren't all FlaskForms
    (plain delete/adjust buttons, fetch() calls). Accepts the token from the
    form or an X-CSRFToken header, and honours WTF_CSRF_ENABLED like Flask-WTF."""
    if request.method != 'POST' or not current_app.config.get('WTF_CSRF_ENABLED', True):
        return
    token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
    try:
        validate_csrf(token)
    except ValidationError:
        abort(400, 'The form expired. Reload the page and try again.')
