from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import login_required
from datetime import datetime, date
import os, uuid

from garagesystem import db
from garagesystem.models import Car, MileageLog
from garagesystem.cars.forms import PlateSearchForm, AddCarForm, EditCarForm, AddMileageForm
from garagesystem.cars.utils import (
    parse_irish_plate, lookup_vehicle_api, normalize_fuel_type, normalize_transmission,
    fetch_car_image, convert_mileage_to_km, estimate_mileage_at_date, compute_car_insights,
    schedule_item_status,
)
from garagesystem.upkeep.forms import FuelLogForm, ScheduleForm, SCHEDULE_PRESETS

cars = Blueprint('cars', __name__)


def _sync_purchase_mileage_log(car):
    """Keep the auto-created 'Mileage at purchase' MileageLog in sync with the
    car's purchase_date/purchase_mileage, mirroring how a service event's
    mileage log stays in sync via source_event_id (see events._sync_mileage_log).
    """
    linked = MileageLog.query.filter_by(car_id=car.id, is_purchase_mileage=True).first()

    if car.purchase_date is None or car.purchase_mileage is None:
        if linked:
            db.session.delete(linked)
        return

    if linked:
        linked.date = car.purchase_date
        linked.mileage = car.purchase_mileage
        return

    # Adopt a matching unlinked log rather than creating a duplicate entry.
    existing = MileageLog.query.filter_by(
        car_id=car.id,
        date=car.purchase_date,
        mileage=car.purchase_mileage,
        source_event_id=None,
        is_purchase_mileage=False,
    ).first()
    if existing:
        existing.is_purchase_mileage = True
        existing.notes = 'Mileage at purchase'
        return

    db.session.add(MileageLog(
        car_id=car.id,
        mileage=car.purchase_mileage,
        date=car.purchase_date,
        notes='Mileage at purchase',
        is_purchase_mileage=True,
    ))


@cars.route('/cars')
@login_required
def cars_list():
    all_cars = Car.query.order_by(Car.date_added.desc()).all()
    return render_template('cars/cars_list.html', title='My Cars', cars=all_cars)


@cars.route('/cars/new', methods=['GET', 'POST'])
@login_required
def add_car_step1():
    form = PlateSearchForm()
    if form.validate_on_submit():
        reg = form.registration.data.upper().strip()

        parsed = parse_irish_plate(reg)
        api_data, api_error, api_raw = lookup_vehicle_api(reg)

        # Normalise year to int or None
        year_raw = (api_data or {}).get('year') or parsed.get('year')
        try:
            year = int(year_raw) if year_raw else None
        except (ValueError, TypeError):
            year = None

        prefill = {
            'registration': reg,
            'year': year,
            'parsed': parsed.get('parsed', False),
            'parsed_year_display': parsed.get('year_display', ''),
            'parsed_county': parsed.get('county', ''),
            'lookup_success': False,
            'lookup_description': '',
            'lookup_error': api_error or '',
            'lookup_data': api_raw or '',
        }

        if api_data:
            prefill.update({
                'make': api_data.get('make', ''),
                'model': api_data.get('model', ''),
                'variant': api_data.get('variant', ''),
                'color': api_data.get('colour', ''),
                'fuel_type': normalize_fuel_type(api_data.get('fuel_type', '')),
                'engine_size': api_data.get('engine_size', ''),
                'transmission': normalize_transmission(api_data.get('transmission', '')),
                'vin': api_data.get('vin', ''),
                'lookup_success': True,
                'lookup_description': api_data.get('description', ''),
            })

        session['new_car_prefill'] = prefill
        return redirect(url_for('cars.add_car_details'))

    return render_template('cars/add_car_step1.html', title='Add Car', form=form)


@cars.route('/cars/new/details', methods=['GET', 'POST'])
@login_required
def add_car_details():
    prefill = session.get('new_car_prefill')
    if not prefill:
        return redirect(url_for('cars.add_car_step1'))

    # On GET: pre-populate form from session data; on POST: uses request.form
    form = AddCarForm(data=prefill)

    if form.validate_on_submit():
        car = Car(
            registration=form.registration.data.upper().strip(),
            make=form.make.data.strip(),
            model=form.model.data.strip(),
            variant=form.variant.data.strip() if form.variant.data else None,
            year=form.year.data,
            color=form.color.data or None,
            vin=form.vin.data.upper().strip() if form.vin.data else None,
            engine_size=form.engine_size.data or None,
            fuel_type=form.fuel_type.data or None,
            transmission=form.transmission.data or None,
            current_mileage=convert_mileage_to_km(form.current_mileage.data, form.current_mileage_unit.data),
            purchase_date=form.purchase_date.data,
            purchase_price=form.purchase_price.data,
            purchase_mileage=convert_mileage_to_km(form.purchase_mileage.data, form.purchase_mileage_unit.data),
            notes=form.notes.data or None,
            lookup_data=prefill.get('lookup_data') or None,
            image_url=fetch_car_image(form.make.data.strip(), form.model.data.strip(), form.year.data),
        )
        db.session.add(car)
        db.session.flush()  # assign car.id before creating related rows
        _sync_purchase_mileage_log(car)
        db.session.commit()
        session.pop('new_car_prefill', None)
        flash(f'{car.registration} added successfully.', 'success')
        return redirect(url_for('cars.view_car', car_id=car.id))

    return render_template('cars/add_car.html', title='Add Car', form=form, prefill=prefill)


@cars.route('/cars/<int:car_id>')
@login_required
def view_car(car_id):
    car = Car.query.get_or_404(car_id)
    mileage_form = AddMileageForm()

    # For events with no logged mileage, estimate one for the chart only (never
    # persisted) by interpolating between known mileage readings around its date.
    anchors = [(log.date, log.mileage) for log in car.mileage_logs]
    event_mileages = {}
    for event in car.service_events:
        if event.mileage_at_event:
            event_mileages[event.id] = (event.mileage_at_event, False)
        else:
            estimated = estimate_mileage_at_date(anchors, event.date)
            if estimated is not None:
                event_mileages[event.id] = (estimated, True)

    insights = compute_car_insights(car)
    schedule = [(item, schedule_item_status(item, car, insights['annual_mileage'])) for item in car.schedule_items]
    status_rank = {'overdue': 0, 'due_soon': 1, 'ok': 2, 'unknown': 3}
    schedule.sort(key=lambda r: (status_rank[r[1]['status']], r[1]['due_date'] or date.max, r[0].name))
    have = {i.name.lower() for i in car.schedule_items}

    # Reminder cards are raised on page view, so the car page lists the same
    # cards the whiteboard would show.
    from garagesystem.board.utils import sync_auto_tasks
    sync_auto_tasks()

    return render_template(
        'cars/view_car.html', title=str(car), car=car, mileage_form=mileage_form,
        event_mileages=event_mileages, insights=insights,
        schedule=schedule, schedule_form=ScheduleForm(prefix='sched'),
        presets=[p for p in SCHEDULE_PRESETS if p[0].lower() not in have],
        fuel_form=FuelLogForm(), open_tasks=sorted(car.open_tasks, key=lambda t: (t.status != 'doing', t.position)),
    )


@cars.route('/cars/<int:car_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    form = EditCarForm(obj=car)

    if form.validate_on_submit():
        new_reg = form.registration.data.upper().strip()
        # Check registration uniqueness excluding this car
        existing = Car.query.filter(
            Car.registration == new_reg,
            Car.id != car_id
        ).first()
        if existing:
            form.registration.errors.append('Another car already has this registration.')
        else:
            car.registration = new_reg
            car.make = form.make.data.strip()
            car.model = form.model.data.strip()
            car.variant = form.variant.data.strip() if form.variant.data else None
            car.year = form.year.data
            car.color = form.color.data or None
            car.vin = form.vin.data.upper().strip() if form.vin.data else None
            car.engine_size = form.engine_size.data or None
            car.fuel_type = form.fuel_type.data or None
            car.transmission = form.transmission.data or None
            car.current_mileage = convert_mileage_to_km(form.current_mileage.data, form.current_mileage_unit.data)
            car.purchase_date = form.purchase_date.data
            car.purchase_price = form.purchase_price.data
            car.purchase_mileage = convert_mileage_to_km(form.purchase_mileage.data, form.purchase_mileage_unit.data)
            car.service_interval_km = form.service_interval_km.data
            car.service_interval_months = form.service_interval_months.data
            car.notes = form.notes.data or None
            _sync_purchase_mileage_log(car)
            # Handle custom image upload
            upload = form.image.data
            if upload and upload.filename:
                ext = os.path.splitext(upload.filename)[1].lower()
                filename = f'car_{car.id}_{uuid.uuid4().hex[:8]}{ext}'
                upload_dir = os.path.join(current_app.root_path, 'static', 'car_images')
                os.makedirs(upload_dir, exist_ok=True)
                # Remove old custom image if present
                if car.image_custom:
                    old = os.path.join(upload_dir, car.image_custom)
                    if os.path.exists(old):
                        os.remove(old)
                upload.save(os.path.join(upload_dir, filename))
                car.image_custom = filename
            # Refresh auto image if make/model changed (only used as fallback)
            if car.make != form.make.data.strip() or car.model != form.model.data.strip() or not car.image_url:
                car.image_url = fetch_car_image(form.make.data.strip(), form.model.data.strip(), form.year.data)
            car.date_modified = datetime.utcnow()
            db.session.commit()
            flash('Car updated.', 'success')
            return redirect(url_for('cars.view_car', car_id=car.id))

    return render_template('cars/edit_car.html', title='Edit Car', form=form, car=car)


@cars.route('/cars/<int:car_id>/delete', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    reg = car.registration
    db.session.delete(car)
    db.session.commit()
    flash(f'{reg} deleted.', 'success')
    return redirect(url_for('cars.cars_list'))


@cars.route('/cars/<int:car_id>/mileage/add', methods=['POST'])
@login_required
def add_mileage(car_id):
    car = Car.query.get_or_404(car_id)
    form = AddMileageForm()
    if form.validate_on_submit():
        mileage_km = convert_mileage_to_km(form.mileage.data, form.mileage_unit.data)
        log = MileageLog(
            car_id=car_id,
            mileage=mileage_km,
            date=form.date.data,
            notes=form.notes.data or None,
        )
        db.session.add(log)
        if car.current_mileage is None or mileage_km > car.current_mileage:
            car.current_mileage = mileage_km
        db.session.commit()
        flash(f'Mileage of {mileage_km:,} km logged.', 'success')
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, 'danger')
    return redirect(url_for('cars.view_car', car_id=car_id))


@cars.route('/cars/<int:car_id>/mileage/<int:log_id>/delete', methods=['POST'])
@login_required
def delete_mileage(car_id, log_id):
    log = MileageLog.query.get_or_404(log_id)
    if log.car_id != car_id:
        flash('Not found.', 'danger')
        return redirect(url_for('cars.view_car', car_id=car_id))
    db.session.delete(log)
    db.session.commit()
    flash('Mileage log entry deleted.', 'success')
    return redirect(url_for('cars.view_car', car_id=car_id))


@cars.route('/cars/lookup')
@login_required
def lookup_plate():
    """AJAX endpoint: parse an Irish plate and optionally call an external API."""
    reg = request.args.get('plate', '').strip()
    if not reg:
        return jsonify({'success': False, 'message': 'No plate provided.'})

    parsed = parse_irish_plate(reg)
    api_data = lookup_vehicle_api(reg)
    if api_data:
        parsed['api_data'] = api_data

    return jsonify({'success': True, 'data': parsed})
