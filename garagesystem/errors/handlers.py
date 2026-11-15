from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, flash, jsonify, url_for
from flask_wtf.csrf import CSRFError
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


@errors.app_errorhandler(CSRFError)
def csrf_error(error):
    """A POST without a valid CSRF token: usually a form left open across a
    logout or server restart. Send the person back to retry rather than
    showing a bare 400."""
    if request.is_json or request.accept_mimetypes.best == 'application/json':
        return jsonify({'ok': False, 'error': 'Your session expired. Reload the page and try again.'}), 400
    flash('That form had expired, so nothing was saved. Please try again.', 'warning')
    back = request.referrer
    # Only bounce back to a page on this site.
    if back and urlparse(back).netloc == request.host:
        return redirect(back)
    return redirect(url_for('main.home'))
