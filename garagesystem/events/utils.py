from io import BytesIO
import os
from urllib.parse import urlparse
from flask import render_template, current_app, url_for
from xhtml2pdf import pisa


def _link_callback(uri, rel):
    """Resolve template URLs (e.g. /static/eu-strip.svg) to absolute file paths for xhtml2pdf."""
    if uri.startswith('http://') or uri.startswith('https://') or uri.startswith('file://'):
        return uri

    static_url = url_for('static', filename='').rstrip('/')  # e.g. '/static'
    static_root = current_app.static_folder

    path = urlparse(uri).path or uri
    if path.startswith(static_url + '/'):
        rel_path = path[len(static_url) + 1:]
        full = os.path.normpath(os.path.join(static_root, rel_path))
        if os.path.isfile(full):
            return full

    # Fallback: try treating uri as already an absolute filesystem path
    if os.path.isfile(uri):
        return uri
    return uri


def generate_event_pdf(event, car):
    """Render the event PDF template and return a BytesIO buffer, or None on error."""
    try:
        html = render_template('events/event_pdf.html', event=event, car=car)
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(src=html, dest=pdf_buffer, link_callback=_link_callback)
        if pisa_status.err:
            current_app.logger.error(f'xhtml2pdf error: {pisa_status.err}')
            return None
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as exc:
        current_app.logger.error(f'PDF generation exception: {exc}')
        return None
