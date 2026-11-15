"""Automatic whiteboard cards.

Things the app already knows are coming due (servicing, NCT, motor tax,
insurance, maintenance schedule items, low shelf stock) are put on the board
as cards, so the board is the one list of what needs doing.

Each auto card has a source_key of the form "<subject>|<cycle>":
- subject names the thing, e.g. "schedule:12" or "tax:3"
- cycle names this occurrence of it, e.g. the date it was last done

A card is raised at most once per cycle, so dismissing or finishing a card
doesn't make it come straight back. When the cycle moves on (the work was
logged as an event, the tax was renewed, the stock was topped up), any card
still open for the old cycle is resolved automatically.
"""
from datetime import date as _date, datetime

from garagesystem import db
from garagesystem.models import Car, StockItem, Task
from garagesystem.cars.utils import (
    compute_car_insights, schedule_item_status, DUE_SOON_DAYS, DUE_SOON_KM,
)

AUTO_COLOURS = {
    'service': 'blue', 'schedule': 'blue',
    'nct': 'pink', 'tax': 'pink', 'insurance': 'pink',
    'stock': 'green',
}


def _spec(subject, cycle, source, title, *, car_id=None, due_date=None, due_mileage=None,
          due_soon=True, overdue=False, notes=None, schedule_id=None, stock_item_id=None):
    return {
        'subject': subject,
        'key': f'{subject}|{cycle}',
        'source': source,
        'title': title,
        'car_id': car_id,
        'due_date': due_date,
        'due_mileage': due_mileage,
        'due_soon': due_soon,
        'overdue': overdue,
        'notes': notes,
        'schedule_id': schedule_id,
        'stock_item_id': stock_item_id,
    }


def _date_soon(d, today):
    return d is not None and (d - today).days <= DUE_SOON_DAYS


def car_due_specs(car, today=None):
    """Everything currently tracked for this car, due soon or not.

    A subject is left out when there's nothing to remind about, e.g. the NCT
    is already booked, which resolves any card still open for it.
    """
    today = today or _date.today()
    insights = compute_car_insights(car, today)
    latest = car.latest_mileage
    specs = []

    ns = insights['next_service']
    if ns and not ns.get('booked_date') and ns.get('basis_date'):
        km_left = (ns['due_mileage'] - latest) if (ns['due_mileage'] is not None and latest is not None) else None
        soon = ns['overdue'] or _date_soon(ns['due_date'], today) or (km_left is not None and km_left <= DUE_SOON_KM)
        specs.append(_spec(
            f'service:{car.id}', ns['basis_date'].isoformat(), 'service', 'Service due',
            car_id=car.id, due_date=ns['due_date'], due_mileage=ns['due_mileage'],
            due_soon=soon, overdue=ns['overdue'],
        ))

    nct = insights['nct']
    if nct and not nct.get('booked_date'):
        if nct['status'] == 'retest_required':
            specs.append(_spec(
                f'nct:{car.id}', f"retest-{nct['basis_date'].isoformat()}", 'nct', 'NCT retest',
                car_id=car.id, overdue=True,
                notes=f"Failed the NCT on {nct['basis_date'].strftime('%d/%m/%Y')}. Fix the fail items and book the retest.",
            ))
        elif nct['status'] == 'overdue_unknown':
            specs.append(_spec(
                f'nct:{car.id}', 'unknown', 'nct', 'NCT: none on record',
                car_id=car.id, overdue=True,
                notes='No NCT is on record and the car is old enough to need one. Add the last NCT as an event, or book one.',
            ))
        elif nct.get('due_date'):
            cycle = nct['basis_date'].isoformat() if nct.get('basis_date') else 'first'
            specs.append(_spec(
                f'nct:{car.id}', cycle, 'nct', 'NCT due',
                car_id=car.id, due_date=nct['due_date'],
                due_soon=nct['overdue'] or _date_soon(nct['due_date'], today), overdue=nct['overdue'],
            ))

    for event_type, source, title in (('Tax', 'tax', 'Motor tax renewal'), ('Insurance', 'insurance', 'Insurance renewal')):
        r = insights['motor_tax' if source == 'tax' else 'insurance']
        if r:
            specs.append(_spec(
                f'{source}:{car.id}', r['expiry_date'].isoformat(), source, title,
                car_id=car.id, due_date=r['expiry_date'], due_soon=r['due_soon'], overdue=r['expired'],
            ))

    for item in car.schedule_items:
        st = schedule_item_status(item, car, insights['annual_mileage'], today)
        if st['status'] == 'unknown':
            continue
        cycle = st['basis_date'].isoformat() if st['basis_date'] else f"km{st['basis_mileage']}"
        specs.append(_spec(
            f'schedule:{item.id}', cycle, 'schedule', item.name,
            car_id=car.id, due_date=st['due_date'], due_mileage=st['due_mileage'],
            due_soon=st['due_soon'], overdue=st['overdue'], schedule_id=item.id,
            notes=item.notes,
        ))
    return specs


def stock_due_specs():
    specs = []
    for item in StockItem.query.all():
        if not item.is_low:
            continue
        cycle = item.last_restocked.isoformat(timespec='seconds') if item.last_restocked else 'initial'
        specs.append(_spec(
            f'stock:{item.id}', cycle, 'stock', f'Restock {item.name}',
            stock_item_id=item.id,
            notes=f'{item.quantity:g} {item.unit} left on the shelf.',
        ))
    return specs


def _next_position(status):
    top = db.session.query(db.func.max(Task.position)).filter(Task.status == status).scalar()
    return (top or 0) + 1


def sync_auto_tasks(today=None):
    """Raise, refresh and resolve automatic cards. Commits if anything changed.
    Returns the number of new cards."""
    today = today or _date.today()
    specs = []
    for car in Car.query.all():
        specs.extend(car_due_specs(car, today))
    specs.extend(stock_due_specs())
    by_subject = {s['subject']: s for s in specs}

    changed = False
    auto_tasks = Task.query.filter(Task.source != 'manual', Task.source_key.isnot(None)).all()
    existing_keys = {t.source_key for t in auto_tasks}

    for task in auto_tasks:
        if not task.is_open:
            continue
        subject = task.source_key.split('|', 1)[0]
        spec = by_subject.get(subject)
        if spec is None or spec['key'] != task.source_key:
            # Moved on to a new cycle (or no longer tracked): this one's dealt with.
            task.status = 'done'
            task.completed_at = datetime.utcnow()
            changed = True
            continue
        # Same cycle: keep the projected due date/mileage current.
        if task.due_date != spec['due_date'] or task.due_mileage != spec['due_mileage']:
            task.due_date = spec['due_date']
            task.due_mileage = spec['due_mileage']
            changed = True
        if spec['overdue'] and task.priority != 'high':
            task.priority = 'high'
            changed = True

    created = 0
    for spec in specs:
        if not spec['due_soon'] or spec['key'] in existing_keys:
            continue
        db.session.add(Task(
            car_id=spec['car_id'],
            title=spec['title'],
            notes=spec['notes'],
            status='todo',
            priority='high' if spec['overdue'] else 'normal',
            colour=AUTO_COLOURS.get(spec['source'], 'yellow'),
            due_date=spec['due_date'],
            due_mileage=spec['due_mileage'],
            position=_next_position('todo') + created,
            source=spec['source'],
            source_key=spec['key'],
            schedule_id=spec['schedule_id'],
            stock_item_id=spec['stock_item_id'],
        ))
        existing_keys.add(spec['key'])
        created += 1
        changed = True

    if changed:
        db.session.commit()
    return created


def task_urgency(task, today=None):
    """'overdue', 'soon' or None, for colouring the card's due line."""
    today = today or _date.today()
    # Undated reminders raised as overdue (NCT retest, no NCT on record).
    if task.is_auto and task.priority == 'high' and task.due_date is None and task.due_mileage is None:
        return 'overdue'
    latest = task.car.latest_mileage if task.car else None
    km_left = (task.due_mileage - latest) if (task.due_mileage is not None and latest is not None) else None
    if (task.due_date and task.due_date < today) or (km_left is not None and km_left <= 0):
        return 'overdue'
    if (task.due_date and (task.due_date - today).days <= DUE_SOON_DAYS) or (km_left is not None and km_left <= DUE_SOON_KM):
        return 'soon'
    return None


# Event type to pre-select when a card is logged as a service event.
SOURCE_EVENT_TYPES = {
    'service': 'Service', 'nct': 'NCT', 'tax': 'Tax', 'insurance': 'Insurance',
    'schedule': 'Maintenance', 'manual': 'Maintenance',
}
