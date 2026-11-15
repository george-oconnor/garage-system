"""Per-car upkeep: fuel log, maintenance schedule and the full history PDF."""
import os
from datetime import date as _date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file, current_app
from flask_login import login_required

from garagesystem import db
from garagesystem.models import Car, FuelLog, MileageLog, MaintenanceSchedule, Task
from garagesystem.upkeep.forms import FuelLogForm, ScheduleForm, SCHEDULE_PRESETS
from garagesystem.cars.utils import convert_mileage_to_km, compute_car_insights, schedule_item_status
from garagesystem.upkeep.history import generate_history_pdf

upkeep = Blueprint('upkeep', __name__)




def _back_to_car(car_id, anchor=''):
    return redirect(url_for('cars.view_car', car_id=car_id) + anchor)


def _flash_errors(form):
    for errors in form.errors.values():
        for e in errors:
            flash(e, 'danger')


# ── Fuel log ────────────────────────────────────────────────

def _sync_fuel_mileage_log(car, fuel):
    """Every fill-up with an odometer reading is also a mileage reading, so it
    feeds the annual-mileage estimate. Mirrors events._sync_mileage_log."""
    linked = MileageLog.query.filter_by(source_fuel_id=fuel.id).first()
    if fuel.mileage is None:
        if linked:
            db.session.delete(linked)
        return
    note = 'Auto-logged from fill-up'
    if linked:
        linked.date, linked.mileage, linked.notes = fuel.date, fuel.mileage, note
        return
    existing = MileageLog.query.filter_by(
        car_id=car.id, date=fuel.date, mileage=fuel.mileage,
        source_event_id=None, source_fuel_id=None, is_purchase_mileage=False,
    ).first()
    if existing:
        existing.source_fuel_id = fuel.id
        return
    db.session.add(MileageLog(car_id=car.id, date=fuel.date, mileage=fuel.mileage,
                              notes=note, source_fuel_id=fuel.id))


@upkeep.route('/cars/<int:car_id>/fuel/add', methods=['POST'])
@login_required
def add_fuel(car_id):
    car = Car.query.get_or_404(car_id)
    form = FuelLogForm()
    if form.validate_on_submit():
        mileage = convert_mileage_to_km(form.mileage.data, form.mileage_unit.data)
        fuel = FuelLog(
            car_id=car.id,
            date=form.date.data,
            mileage=mileage,
            litres=form.litres.data,
            total_cost=form.total_cost.data,
            full_tank=bool(form.full_tank.data),
            station=(form.station.data or '').strip() or None,
            notes=(form.notes.data or '').strip() or None,
        )
        db.session.add(fuel)
        db.session.flush()
        _sync_fuel_mileage_log(car, fuel)
        if mileage and (car.current_mileage is None or mileage > car.current_mileage):
            car.current_mileage = mileage
        db.session.commit()
        flash(f'Fill-up of {fuel.litres:g} L logged.', 'success')
    else:
        _flash_errors(form)
    return _back_to_car(car.id, '#fuel')


@upkeep.route('/cars/<int:car_id>/fuel/<int:fuel_id>/delete', methods=['POST'])
@login_required
def delete_fuel(car_id, fuel_id):
    fuel = FuelLog.query.get_or_404(fuel_id)
    if fuel.car_id != car_id:
        abort(404)
    MileageLog.query.filter_by(source_fuel_id=fuel.id).delete()
    db.session.delete(fuel)
    db.session.commit()
    flash('Fill-up removed.', 'success')
    return _back_to_car(car_id, '#fuel')


# ── Maintenance schedule ────────────────────────────────────

def _apply_schedule_form(item, form):
    item.name = form.name.data.strip()
    item.interval_km = form.interval_km.data
    item.interval_months = form.interval_months.data
    item.last_done_date = form.last_done_date.data
    item.last_done_mileage = convert_mileage_to_km(form.last_done_mileage.data, form.last_done_mileage_unit.data)
    item.notes = (form.notes.data or '').strip() or None


@upkeep.route('/cars/<int:car_id>/schedule/add', methods=['POST'])
@login_required
def add_schedule(car_id):
    car = Car.query.get_or_404(car_id)
    form = ScheduleForm(prefix='sched')
    if form.validate_on_submit():
        item = MaintenanceSchedule(car_id=car.id)
        _apply_schedule_form(item, form)
        db.session.add(item)
        db.session.commit()
        flash(f'{item.name} added to the maintenance schedule.', 'success')
    else:
        _flash_errors(form)
    return _back_to_car(car.id, '#schedule')


@upkeep.route('/cars/<int:car_id>/schedule/presets', methods=['POST'])
@login_required
def add_schedule_presets(car_id):
    car = Car.query.get_or_404(car_id)
    chosen = set(request.form.getlist('preset'))
    have = {i.name.lower() for i in car.schedule_items}
    added = 0
    for name, km, months, note in SCHEDULE_PRESETS:
        if name in chosen and name.lower() not in have:
            db.session.add(MaintenanceSchedule(car_id=car.id, name=name, interval_km=km,
                                               interval_months=months, notes=note))
            added += 1
    db.session.commit()
    if added:
        flash(f'Added {added} item(s). Check the intervals against the handbook, and set when each '
              'was last done so they can be tracked.', 'success')
    return _back_to_car(car.id, '#schedule')


@upkeep.route('/cars/<int:car_id>/schedule/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_schedule(car_id, item_id):
    item = MaintenanceSchedule.query.get_or_404(item_id)
    if item.car_id != car_id:
        abort(404)
    car = item.car
    form = ScheduleForm(obj=item)
    if form.validate_on_submit():
        _apply_schedule_form(item, form)
        db.session.commit()
        flash(f'{item.name} updated.', 'success')
        return _back_to_car(car.id, '#schedule')
    insights = compute_car_insights(car)
    status = schedule_item_status(item, car, insights['annual_mileage'])
    events = sorted(item.events, key=lambda e: e.date, reverse=True)
    return render_template('upkeep/edit_schedule.html', title=f'Edit {item.name}', form=form,
                           item=item, car=car, status=status, events=events)


@upkeep.route('/cars/<int:car_id>/schedule/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_schedule(car_id, item_id):
    item = MaintenanceSchedule.query.get_or_404(item_id)
    if item.car_id != car_id:
        abort(404)
    name = item.name
    Task.query.filter_by(schedule_id=item.id).update({'schedule_id': None})
    db.session.delete(item)
    db.session.commit()
    flash(f'{name} removed from the schedule.', 'success')
    return _back_to_car(car_id, '#schedule')


# ── Full history PDF ────────────────────────────────────────

@upkeep.route('/cars/<int:car_id>/history.pdf')
@login_required
def history_pdf(car_id):
    car = Car.query.get_or_404(car_id)
    def flag(name, default):
        # The options form sends a hidden "0" plus the checkbox's "1" when ticked.
        values = request.args.getlist(name)
        return '1' in values if values else default

    include_costs = flag('costs', True)
    include_certs = flag('certs', True)
    include_invoices = flag('invoices', False)
    buf = generate_history_pdf(car, include_costs=include_costs,
                               include_certs=include_certs, include_invoices=include_invoices)
    if buf is None:
        flash('Failed to generate the history PDF. Check the server logs for details.', 'danger')
        return _back_to_car(car.id)
    filename = f'{car.registration}_service_history_{_date.today().strftime("%Y%m%d")}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)
