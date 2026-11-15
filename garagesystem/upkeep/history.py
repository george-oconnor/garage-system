"""Full service history PDF, for selling the car or for your own records.

The report itself is rendered with xhtml2pdf, like the single-event PDF.
Uploaded NCT certificates (and optionally garage invoices) are then appended
after it as their original pages, with a bookmark for each.
"""
import os
from datetime import date as _date
from io import BytesIO

from flask import render_template, current_app
from pypdf import PdfWriter
from xhtml2pdf import pisa

from garagesystem.cars.utils import compute_car_insights, schedule_item_status
from garagesystem.events.utils import _link_callback


def _attachments(car, include_certs, include_invoices):
    """(event, label, path) for each attached PDF that exists on disk, oldest first."""
    static = os.path.join(current_app.root_path, 'static')
    found = []
    for e in sorted(car.service_events, key=lambda e: e.date):
        if include_certs and e.event_type == 'NCT' and e.nct_cert_filename:
            path = os.path.join(static, 'nct_certs', e.nct_cert_filename)
            if os.path.isfile(path):
                result = f' ({e.nct_result})' if e.nct_result else ''
                found.append((e, f"NCT certificate {e.date.strftime('%d/%m/%Y')}{result}", path))
        if include_invoices and e.invoice_filename:
            path = os.path.join(static, 'invoices', e.invoice_filename)
            if os.path.isfile(path):
                found.append((e, f"Invoice: {e.title} {e.date.strftime('%d/%m/%Y')}", path))
    return found


def generate_history_pdf(car, include_costs=True, include_certs=True, include_invoices=False):
    """Return a BytesIO with the full history PDF, or None on error."""
    try:
        today = _date.today()
        insights = compute_car_insights(car, today)
        schedule = [(item, schedule_item_status(item, car, insights['annual_mileage'], today))
                    for item in car.schedule_items]
        events = sorted(car.service_events, key=lambda e: e.date, reverse=True)
        past_events = [e for e in events if e.date <= today]
        nct_events = [e for e in past_events if e.event_type == 'NCT']
        attachments = _attachments(car, include_certs, include_invoices)

        html = render_template(
            'upkeep/history_pdf.html', car=car, insights=insights, schedule=schedule,
            events=past_events, nct_events=nct_events,
            mileage_logs=sorted(car.mileage_logs, key=lambda l: l.date, reverse=True),
            attachments=attachments, attached_ids={e.id for e, _l, _p in attachments},
            include_costs=include_costs, today=today,
        )
        report = BytesIO()
        status = pisa.CreatePDF(src=html, dest=report, link_callback=_link_callback)
        if status.err:
            current_app.logger.error(f'xhtml2pdf error (history PDF): {status.err}')
            return None
        report.seek(0)

        if not attachments:
            return report

        writer = PdfWriter()
        writer.append(report, outline_item='Service history')
        for _event, label, path in attachments:
            try:
                writer.append(path, outline_item=label)
            except Exception as exc:  # a damaged or encrypted upload shouldn't sink the report
                current_app.logger.warning(f'Could not append {path} to history PDF: {exc}')
        out = BytesIO()
        writer.write(out)
        out.seek(0)
        return out
    except Exception as exc:
        current_app.logger.exception(f'History PDF generation failed: {exc}')
        return None
