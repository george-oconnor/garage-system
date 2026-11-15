from datetime import date

from garagesystem.cars.utils import (
    project_due, schedule_item_status, renewal_status, compute_fuel_stats, compute_car_insights,
)
from garagesystem.models import MaintenanceSchedule, FuelLog
from tests.factories import make_car, log_mileage, make_event

TODAY = date(2026, 11, 15)


def test_project_due_takes_whichever_comes_first():
    # 10,000 km/yr, done 6 months ago at 50,000 km. Every 12 months or 5,000 km:
    # the distance limit comes first, about now.
    due = project_due(date(2026, 5, 15), 50000, 12, 5000,
                      TODAY, 55000, 10000, TODAY)
    assert due['due_mileage'] == 55000
    assert due['km_left'] == 0
    assert due['overdue'] is True
    assert due['due_date'] == TODAY


def test_project_due_soon_window():
    due = project_due(date(2025, 12, 1), None, 12, None, None, None, None, TODAY)
    assert due['due_date'] == date(2026, 12, 1)
    assert due['days_left'] == 16
    assert due['due_soon'] and not due['overdue']


def test_schedule_item_uses_latest_linked_event(db):
    car = make_car()
    log_mileage(car, date(2024, 1, 1), 40000)
    log_mileage(car, TODAY, 60000)
    item = MaintenanceSchedule(car_id=car.id, name='Brake fluid', interval_months=24,
                               last_done_date=date(2022, 1, 1))
    db.session.add(item)
    old = make_event(car, date(2023, 6, 1), 'Maintenance')
    new = make_event(car, date(2025, 6, 1), 'Maintenance')
    future = make_event(car, date(2027, 1, 1), 'Maintenance')  # booked, not done yet
    item.events.extend([old, new, future])
    db.session.flush()

    st = schedule_item_status(item, car, annual_mileage=10000, today=TODAY)
    assert st['basis_event'] is new
    assert st['due_date'] == date(2027, 6, 1)
    assert st['status'] == 'ok'


def test_schedule_item_without_history_is_unknown(db):
    car = make_car()
    item = MaintenanceSchedule(car_id=car.id, name='Coolant', interval_km=100000)
    db.session.add(item)
    db.session.flush()
    assert schedule_item_status(item, car, today=TODAY)['status'] == 'unknown'


def test_renewal_status_uses_latest_expiry(db):
    car = make_car()
    make_event(car, date(2025, 11, 1), 'Tax', expiry_date=date(2026, 10, 31))
    make_event(car, date(2026, 11, 1), 'Tax', expiry_date=date(2026, 12, 1))
    r = renewal_status(car, 'Tax', TODAY)
    assert r['expiry_date'] == date(2026, 12, 1)
    assert r['due_soon'] and not r['expired']
    assert renewal_status(car, 'Insurance', TODAY) is None


def _fill(car, when, km, litres, cost, full=True):
    return FuelLog(car_id=car.id, date=when, mileage=km, litres=litres, total_cost=cost, full_tank=full)


def test_fuel_economy_full_to_full_with_partial(db):
    car = make_car()
    logs = [
        _fill(car, date(2026, 1, 1), 10000, 40, 70),            # baseline full tank
        _fill(car, date(2026, 1, 10), 10300, 10, 18, full=False),  # partial
        _fill(car, date(2026, 1, 20), 10800, 30, 54),           # full: 40 L over 800 km
        _fill(car, date(2026, 2, 1), 11300, 35, 63),            # full: 35 L over 500 km
    ]
    for i, f in enumerate(logs, start=1):
        f.id = i
    stats = compute_fuel_stats(logs)
    assert stats['per_log'] == {3: 5.0, 4: 7.0}
    assert stats['avg_l_per_100km'] == round(75 / 1300 * 100, 2)
    assert stats['cost_per_km'] == round((18 + 54 + 63) / 1300, 3)
    assert stats['last_l_per_100km'] == 7.0
    assert stats['total_spend'] == 205


def test_fuel_fill_without_odometer_breaks_chain(db):
    car = make_car()
    logs = [
        _fill(car, date(2026, 1, 1), 10000, 40, 70),
        _fill(car, date(2026, 1, 10), None, 20, 36),
        _fill(car, date(2026, 1, 20), 10800, 30, 54),
    ]
    for i, f in enumerate(logs, start=1):
        f.id = i
    stats = compute_fuel_stats(logs)
    assert stats['avg_l_per_100km'] is None
    assert stats['per_log'] == {}


def test_insights_running_cost_adds_fuel(db):
    car = make_car(purchase_mileage=10000)
    log_mileage(car, date(2026, 1, 1), 10000)
    log_mileage(car, date(2026, 2, 1), 11000)
    make_event(car, date(2026, 1, 15), 'Repair', total_cost_override=100, provider_type='ThirdParty')
    for f in (_fill(car, date(2026, 1, 1), 10000, 40, 70), _fill(car, date(2026, 2, 1), 11000, 50, 90)):
        db.session.add(f)
    db.session.flush()
    ins = compute_car_insights(car, TODAY)
    assert ins['cost_per_km'] == 0.1
    assert ins['fuel_cost_per_km'] == 0.09
    assert ins['total_cost_per_km'] == 0.19
