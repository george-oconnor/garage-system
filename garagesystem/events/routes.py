from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required
from datetime import datetime
import os, uuid

from garagesystem import db
from garagesystem.models import (
    Car, ServiceEvent, EventLineItem, MileageLog, MaintenanceSchedule, StockItem, Task,
)
from garagesystem.events.forms import AddEventForm, EditEventForm, AddLineItemForm
from garagesystem.events.utils import generate_event_pdf
from garagesystem.cars.utils import convert_mileage_to_km

events = Blueprint('events', __name__)


NCT_CERT_SUBDIR = 'nct_certs'
INVOICE_SUBDIR = 'invoices'


def _nct_cert_dir():
    return os.path.join(current_app.root_path, 'static', NCT_CERT_SUBDIR)


def _invoice_dir():
    return os.path.join(current_app.root_path, 'static', INVOICE_SUBDIR)


def _save_nct_cert(upload, event_id):
    """Save an uploaded NCT cert PDF and return the stored filename."""
    os.makedirs(_nct_cert_dir(), exist_ok=True)
    filename = f'nct_{event_id}_{uuid.uuid4().hex[:8]}.pdf'
    upload.save(os.path.join(_nct_cert_dir(), filename))
    return filename


def _delete_nct_cert(filename):
    if not filename:
        return
    path = os.path.join(_nct_cert_dir(), filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as exc:
            current_app.logger.warning(f'Could not remove NCT cert {path}: {exc}')


def _save_invoice(upload, event_id):
    """Save an uploaded invoice PDF and return the stored filename."""
    os.makedirs(_invoice_dir(), exist_ok=True)
    filename = f'invoice_{event_id}_{uuid.uuid4().hex[:8]}.pdf'
    upload.save(os.path.join(_invoice_dir(), filename))
    return filename


def _delete_invoice(filename):
    if not filename:
        return
    path = os.path.join(_invoice_dir(), filename)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as exc:
            current_app.logger.warning(f'Could not remove invoice {path}: {exc}')


def _sync_mileage_log(car, event):
    """Keep the auto-created MileageLog for this event in sync with its date / mileage.

    - Uses `MileageLog.source_event_id` as the link.
    - If the event has both date and mileage, create or update the linked log.
    - If the event has neither, delete any existing linked log.
    - When creating a fresh log, if a log with the same (date, mileage) already exists
      but is unlinked, adopt it rather than creating a duplicate.
    """
    linked = MileageLog.query.filter_by(source_event_id=event.id).first()

    if not event.mileage_at_event or not event.date:
        # Event no longer represents a mileage reading — drop the linked log.
        if linked:
            db.session.delete(linked)
        return

    note = f'Auto-logged from service event: {event.title}'

    if linked:
        # Update in place so date/mileage/title changes propagate.
        linked.car_id = car.id
        linked.date = event.date
        linked.mileage = event.mileage_at_event
        linked.notes = note
        return

    # No linked log yet — try to adopt a matching unlinked log before creating one.
    existing = MileageLog.query.filter_by(
        car_id=car.id,
        date=event.date,
        mileage=event.mileage_at_event,
        source_event_id=None,
    ).first()
    if existing:
        existing.source_event_id = event.id
        existing.notes = note
        return

    db.session.add(MileageLog(
        car_id=car.id,
        mileage=event.mileage_at_event,
        date=event.date,
        notes=note,
        source_event_id=event.id,
    ))


RENEWAL_TYPES = ('Tax', 'Insurance')


def _schedule_choices(car):
    # The Service item comes first; Service events count towards it anyway.
    items = sorted(car.schedule_items, key=lambda i: (not i.is_service, i.name))
    return [(i.id, f'{i.name} (automatic for Service events)' if i.is_service else i.name) for i in items]


def _set_schedule_items(event, car, ids):
    wanted = set(ids or [])
    event.schedule_items = [i for i in car.schedule_items if i.id in wanted]


def _stock_choices():
    items = StockItem.query.order_by(StockItem.category, StockItem.name).all()
    return [(0, '— Not from the shelf —')] + [
        (s.id, f'{s.name} · {s.quantity:g} {s.unit} left') for s in items
    ]


def _take_from_stock(stock, quantity):
    """Deduct from the shelf. Returns False (and changes nothing) if there isn't enough."""
    if stock.quantity + 1e-9 < quantity:
        return False
    stock.quantity = round(stock.quantity - quantity, 3)
    return True


def _return_stock(item):
    """Put a removed line item's quantity back on the shelf."""
    if item.stock_item_id:
        stock = db.session.get(StockItem, item.stock_item_id)
        if stock:
            stock.quantity = round(stock.quantity + item.quantity, 3)


def _complete_task_with_event(task, event):
    """Close a whiteboard card that's been logged as this event, turning its
    parts list into line items."""
    task.status = 'done'
    task.completed_at = task.completed_at or datetime.utcnow()
    task.event_id = event.id
    if event.event_type == 'NCT' or event.uses_invoice or event.total_cost_override is not None:
        return []
    short = []
    for part in task.parts:
        item = EventLineItem(
            event_id=event.id,
            description=part.description,
            item_type='Parts',
            part_number=part.part_number,
            quantity=part.quantity,
            unit_cost=part.unit_cost or 0,
        )
        stock = part.stock_item
        if stock:
            if item.unit_cost == 0 and stock.unit_cost:
                item.unit_cost = stock.unit_cost
            if _take_from_stock(stock, part.quantity):
                item.stock_item_id = stock.id
            else:
                short.append(stock.name)
        db.session.add(item)
    return short


@events.route('/cars/<int:car_id>/events/new', methods=['GET', 'POST'])
@login_required
def add_event(car_id):
    from garagesystem.board.utils import SOURCE_EVENT_TYPES
    car = Car.query.get_or_404(car_id)
    form = AddEventForm()
    form.schedule_items.choices = _schedule_choices(car)

    # Logging a finished whiteboard card: prefill from the card.
    task = None
    task_id = request.args.get('task', type=int)
    if task_id:
        task = db.session.get(Task, task_id)
        if task is None or task.car_id != car.id:
            task = None
    if task and request.method == 'GET':
        form.title.data = task.title
        form.event_type.data = SOURCE_EVENT_TYPES.get(task.source, 'Maintenance')
        form.notes.data = task.notes
        if task.schedule_id:
            form.schedule_items.data = [task.schedule_id]
        if task.completed_at:
            form.date.data = task.completed_at.date()

    if form.validate_on_submit():
        # NCT tests are always carried out by a third-party test centre.
        is_third_party = form.provider_type.data == 'ThirdParty' or form.event_type.data == 'NCT'
        mileage_km = convert_mileage_to_km(form.mileage_at_event.data, form.mileage_at_event_unit.data)
        event = ServiceEvent(
            car_id=car_id,
            title=form.title.data.strip(),
            event_type=form.event_type.data,
            provider_type='ThirdParty' if form.event_type.data == 'NCT' else form.provider_type.data,
            date=form.date.data,
            mileage_at_event=mileage_km,
            garage_name=(form.garage_name.data.strip() if form.garage_name.data else None) if is_third_party else None,
            garage_address=(form.garage_address.data.strip() if form.garage_address.data else None) if is_third_party else None,
            invoice_number=(form.invoice_number.data.strip() if form.invoice_number.data else None) if is_third_party else None,
            notes=form.notes.data or None,
            total_cost_override=form.total_cost_override.data if is_third_party else None,
            nct_result=(form.nct_result.data or None) if form.event_type.data == 'NCT' else None,
            nct_next_due=(form.nct_next_due.data if form.nct_result.data == 'Pass' else None) if form.event_type.data == 'NCT' else None,
            expiry_date=form.expiry_date.data if form.event_type.data in RENEWAL_TYPES else None,
        )
        _set_schedule_items(event, car, form.schedule_items.data)
        db.session.add(event)
        # Update car mileage if this reading is higher
        if mileage_km:
            if car.current_mileage is None or mileage_km > car.current_mileage:
                car.current_mileage = mileage_km
        db.session.flush()  # assign event.id for FK / filenames
        _sync_mileage_log(car, event)
        # Handle invoice PDF upload (third-party only)
        if is_third_party:
            invoice_upload = form.invoice_pdf.data
            if invoice_upload and getattr(invoice_upload, 'filename', ''):
                event.invoice_filename = _save_invoice(invoice_upload, event.id)
        # Handle NCT cert upload (only if event is NCT)
        if event.event_type == 'NCT':
            upload = form.nct_cert.data
            if upload and getattr(upload, 'filename', ''):
                event.nct_cert_filename = _save_nct_cert(upload, event.id)
        short = _complete_task_with_event(task, event) if task else []
        db.session.commit()
        flash(f'Event "{event.title}" created.', 'success')
        if task:
            flash(f'Whiteboard card "{task.title}" ticked off.', 'info')
        if short:
            flash('Not enough on the shelf for: ' + ', '.join(short)
                  + '. Those line items were added without deducting stock.', 'warning')
        return redirect(url_for('events.view_event', event_id=event.id))

    return render_template('events/add_event.html', title='Add Event', form=form, car=car, task=task)


@events.route('/events/<int:event_id>')
@login_required
def view_event(event_id):
    event = ServiceEvent.query.get_or_404(event_id)
    form = AddLineItemForm()
    form.stock_item_id.choices = _stock_choices()
    stock_data = {s.id: {'name': s.name, 'part_number': s.part_number or '', 'unit_cost': s.unit_cost,
                         'category': s.category, 'unit': s.unit, 'quantity': s.quantity}
                  for s in StockItem.query.all()}
    return render_template(
        'events/view_event.html',
        title=event.title,
        event=event,
        car=event.car,
        form=form,
        stock_data=stock_data,
        tasks=Task.query.filter_by(event_id=event.id).all(),
    )


@events.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    event = ServiceEvent.query.get_or_404(event_id)
    form = EditEventForm(obj=event)
    form.schedule_items.choices = _schedule_choices(event.car)
    if request.method == 'GET':
        form.schedule_items.data = [i.id for i in event.schedule_items]
    if form.validate_on_submit():
        event.title = form.title.data.strip()
        event.event_type = form.event_type.data
        # NCT tests are always carried out by a third-party test centre.
        event.provider_type = 'ThirdParty' if event.event_type == 'NCT' else form.provider_type.data
        event.date = form.date.data
        event.mileage_at_event = convert_mileage_to_km(form.mileage_at_event.data, form.mileage_at_event_unit.data)
        event.notes = form.notes.data or None
        event.date_modified = datetime.utcnow()

        is_third_party = event.provider_type == 'ThirdParty'

        # Third-party fields
        if is_third_party:
            event.garage_name = form.garage_name.data.strip() if form.garage_name.data else None
            event.garage_address = form.garage_address.data.strip() if form.garage_address.data else None
            event.invoice_number = form.invoice_number.data.strip() if form.invoice_number.data else None
            event.total_cost_override = form.total_cost_override.data

            # Remove existing invoice if user asked
            if form.remove_invoice.data and event.invoice_filename:
                _delete_invoice(event.invoice_filename)
                event.invoice_filename = None
            # Replace / add invoice if uploaded
            invoice_upload = form.invoice_pdf.data
            if invoice_upload and getattr(invoice_upload, 'filename', ''):
                if event.invoice_filename:
                    _delete_invoice(event.invoice_filename)
                event.invoice_filename = _save_invoice(invoice_upload, event.id)
                # When an invoice is uploaded, line items no longer make sense — clear them.
                for item in list(event.line_items):
                    _return_stock(item)
                    db.session.delete(item)
        else:
            # Switched to Self — clear third-party-only fields and delete invoice
            if event.invoice_filename:
                _delete_invoice(event.invoice_filename)
                event.invoice_filename = None
            event.garage_name = None
            event.garage_address = None
            event.invoice_number = None
            event.total_cost_override = None

        # NCT-specific handling
        if event.event_type == 'NCT':
            event.nct_result = form.nct_result.data or None
            event.nct_next_due = form.nct_next_due.data if event.nct_result == 'Pass' else None
            # Remove existing cert if user asked
            if form.remove_nct_cert.data and event.nct_cert_filename:
                _delete_nct_cert(event.nct_cert_filename)
                event.nct_cert_filename = None
            # Replace / add cert if uploaded
            upload = form.nct_cert.data
            if upload and getattr(upload, 'filename', ''):
                if event.nct_cert_filename:
                    _delete_nct_cert(event.nct_cert_filename)
                event.nct_cert_filename = _save_nct_cert(upload, event.id)
        else:
            # Event is no longer NCT — clear NCT fields and delete any cert
            if event.nct_cert_filename:
                _delete_nct_cert(event.nct_cert_filename)
                event.nct_cert_filename = None
            event.nct_result = None
            event.nct_next_due = None

        event.expiry_date = form.expiry_date.data if event.event_type in RENEWAL_TYPES else None
        _set_schedule_items(event, event.car, form.schedule_items.data)

        if event.mileage_at_event:
            car = event.car
            if car.current_mileage is None or event.mileage_at_event > car.current_mileage:
                car.current_mileage = event.mileage_at_event

        _sync_mileage_log(event.car, event)
        db.session.commit()
        flash('Event updated.', 'success')
        return redirect(url_for('events.view_event', event_id=event.id))

    return render_template('events/edit_event.html', title='Edit Event', form=form, event=event)


@events.route('/events/<int:event_id>/delete', methods=['POST'])
@login_required
def delete_event(event_id):
    event = ServiceEvent.query.get_or_404(event_id)
    car_id = event.car_id
    title = event.title
    cert_to_remove = event.nct_cert_filename
    invoice_to_remove = event.invoice_filename
    # Remove the auto-created mileage log linked to this event (if any)
    linked_log = MileageLog.query.filter_by(source_event_id=event.id).first()
    if linked_log:
        db.session.delete(linked_log)
    for item in event.line_items:
        _return_stock(item)
    Task.query.filter_by(event_id=event.id).update({'event_id': None})
    db.session.delete(event)
    db.session.commit()
    if cert_to_remove:
        _delete_nct_cert(cert_to_remove)
    if invoice_to_remove:
        _delete_invoice(invoice_to_remove)
    flash(f'Event "{title}" deleted.', 'success')
    return redirect(url_for('cars.view_car', car_id=car_id))


@events.route('/events/<int:event_id>/items/add', methods=['POST'])
@login_required
def add_line_item(event_id):
    event = ServiceEvent.query.get_or_404(event_id)
    # NCT events are always third-party — no line items, use the certificate instead.
    if event.event_type == 'NCT':
        flash('NCT events are handled by a third-party test centre — line items cannot be added.', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))
    # Block line items when the event's cost is captured via an uploaded invoice.
    if event.uses_invoice:
        flash('This event uses an uploaded invoice for its cost — line items cannot be added.', 'warning')
        return redirect(url_for('events.view_event', event_id=event_id))
    form = AddLineItemForm()
    form.stock_item_id.choices = _stock_choices()
    if form.validate_on_submit():
        stock = db.session.get(StockItem, form.stock_item_id.data) if form.stock_item_id.data else None
        item = EventLineItem(
            event_id=event_id,
            description=(form.description.data or '').strip() or (stock.name if stock else ''),
            item_type=form.item_type.data,
            part_number=(form.part_number.data or '').strip() or (stock.part_number if stock else None),
            quantity=form.quantity.data,
            unit_cost=form.unit_cost.data,
            shipping_cost=form.shipping_cost.data or 0,
        )
        if stock:
            if not _take_from_stock(stock, item.quantity):
                flash(f'Only {stock.quantity:g} {stock.unit} of {stock.name} on the shelf. '
                      'Update the shelf or lower the quantity.', 'danger')
                return redirect(url_for('events.view_event', event_id=event_id))
            item.stock_item_id = stock.id
        db.session.add(item)
        db.session.commit()
        if stock:
            flash(f'Line item added. {stock.quantity:g} {stock.unit} of {stock.name} left on the shelf.', 'success')
        else:
            flash('Line item added.', 'success')
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
    return redirect(url_for('events.view_event', event_id=event_id))


@events.route('/events/<int:event_id>/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_line_item(event_id, item_id):
    item = EventLineItem.query.get_or_404(item_id)
    if item.event_id != event_id:
        flash('Item not found on this event.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))
    _return_stock(item)
    db.session.delete(item)
    db.session.commit()
    flash('Line item removed.', 'success')
    return redirect(url_for('events.view_event', event_id=event_id))


@events.route('/events/<int:event_id>/pdf')
@login_required
def download_pdf(event_id):
    event = ServiceEvent.query.get_or_404(event_id)
    car = event.car

    # For NCT events with an uploaded certificate, serve that PDF directly
    if event.event_type == 'NCT' and event.nct_cert_filename:
        cert_path = os.path.join(_nct_cert_dir(), event.nct_cert_filename)
        if os.path.exists(cert_path):
            safe_title = ''.join(c if c.isalnum() or c in '-_' else '_' for c in event.title)[:30]
            filename = f'{car.registration}_{event.date.strftime("%Y%m%d")}_NCT_{safe_title}.pdf'
            return send_file(cert_path, mimetype='application/pdf',
                             as_attachment=True, download_name=filename)
        current_app.logger.warning(f'NCT cert missing on disk for event {event.id}: {cert_path}')

    # For third-party events with an uploaded invoice, serve that PDF directly
    if event.uses_invoice:
        invoice_path = os.path.join(_invoice_dir(), event.invoice_filename)
        if os.path.exists(invoice_path):
            safe_title = ''.join(c if c.isalnum() or c in '-_' else '_' for c in event.title)[:30]
            filename = f'{car.registration}_{event.date.strftime("%Y%m%d")}_Invoice_{safe_title}.pdf'
            return send_file(invoice_path, mimetype='application/pdf',
                             as_attachment=True, download_name=filename)
        current_app.logger.warning(f'Invoice missing on disk for event {event.id}: {invoice_path}')

    pdf_buffer = generate_event_pdf(event, car)
    if pdf_buffer is None:
        flash('Failed to generate PDF. Check server logs for details.', 'danger')
        return redirect(url_for('events.view_event', event_id=event_id))

    safe_title = ''.join(c if c.isalnum() or c in '-_' else '_' for c in event.title)[:30]
    filename = f'{car.registration}_{event.date.strftime("%Y%m%d")}_{safe_title}.pdf'
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)
