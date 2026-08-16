from flask import Blueprint, render_template
from sentry_sdk import last_event_id

errors = Blueprint('errors', __name__)


@errors.app_errorhandler(404)
def error_404(error):
    return render_template('errors/404.html', title='Page Not Found'), 404


@errors.app_errorhandler(403)
def error_403(error):
    return render_template('errors/404.html', title='Access Denied'), 403


@errors.app_errorhandler(500)
def error_500(error):
    event_id = last_event_id()
    return render_template('errors/500.html', title='Server Error', event_id=event_id), 500
