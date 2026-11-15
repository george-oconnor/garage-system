from datetime import date, timedelta

from garagesystem.board.utils import sync_auto_tasks
from garagesystem.models import MaintenanceSchedule, StockItem, Task, TaskPart, EventLineItem
from tests.factories import make_car, make_event

TODAY = date.today()


def _auto(source):
    return Task.query.filter_by(source=source).all()


def test_tax_card_raised_once_and_resolved_on_renewal(db):
    car = make_car(year=TODAY.year)  # too new for an NCT, so the tax card is the only one
    make_event(car, TODAY - timedelta(days=340), 'Tax', expiry_date=TODAY + timedelta(days=10))
    db.session.commit()

    assert sync_auto_tasks() == 1
    [card] = _auto('tax')
    assert card.status == 'todo' and card.car_id == car.id and card.colour == 'pink'

    # Running again doesn't duplicate it
    assert sync_auto_tasks() == 0

    # Dismissed: stays gone for this cycle
    card.status = 'dismissed'
    db.session.commit()
    assert sync_auto_tasks() == 0

    # Renewed: new expiry far away, so no new card
    make_event(car, TODAY, 'Tax', expiry_date=TODAY + timedelta(days=365))
    db.session.commit()
    assert sync_auto_tasks() == 0


def test_open_card_resolves_when_work_logged(db):
    car = make_car()
    item = MaintenanceSchedule(car_id=car.id, name='Brake fluid', interval_months=24,
                               last_done_date=TODAY - timedelta(days=740))
    db.session.add(item)
    db.session.commit()

    sync_auto_tasks()
    [card] = _auto('schedule')
    assert card.is_open and card.priority == 'high'  # overdue
    assert card.schedule_id == item.id

    event = make_event(car, TODAY, 'Maintenance')
    event.schedule_items.append(item)
    db.session.commit()

    sync_auto_tasks()
    db.session.refresh(card)
    assert card.status == 'done'
    assert len(_auto('schedule')) == 1  # and no new one: next due in 2 years


def test_low_stock_card(db):
    stock = StockItem(name='Oil filter', quantity=1, min_quantity=1, unit='pcs')
    db.session.add(stock)
    db.session.commit()
    sync_auto_tasks()
    [card] = _auto('stock')
    assert card.car_id is None and card.title == 'Restock Oil filter'


def test_drag_to_done_and_reorder(client, db):
    car = make_car()
    a = Task(title='A', car_id=car.id, status='todo', position=1)
    b = Task(title='B', car_id=car.id, status='doing', position=1)
    db.session.add_all([a, b])
    db.session.commit()

    r = client.post('/board/move', json={'id': a.id, 'status': 'doing', 'order': [a.id, b.id]})
    assert r.get_json()['ok']
    db.session.refresh(a); db.session.refresh(b)
    assert (a.status, a.position, b.position) == ('doing', 1, 2)

    r = client.post('/board/move', json={'id': a.id, 'status': 'done', 'order': [a.id]})
    data = r.get_json()
    assert data['can_log'] and data['log_url'].endswith(f'/board/tasks/{a.id}/log')
    db.session.refresh(a)
    assert a.status == 'done' and a.completed_at is not None

    assert client.post('/board/move', json={'id': a.id, 'status': 'nope'}).status_code == 400


def test_logging_card_creates_event_with_parts_and_takes_stock(client, db):
    car = make_car()
    filt = StockItem(name='Oil filter', part_number='W712', quantity=3, unit='pcs', unit_cost=8.5)
    db.session.add(filt)
    db.session.flush()
    task = Task(title='Oil change', car_id=car.id, status='done')
    db.session.add(task)
    db.session.flush()
    db.session.add_all([
        TaskPart(task_id=task.id, description='5W-30 5L', quantity=1, unit_cost=40, status='arrived'),
        TaskPart(task_id=task.id, description='Oil filter', quantity=1, stock_item_id=filt.id, status='arrived'),
    ])
    db.session.commit()

    page = client.get(f'/cars/{car.id}/events/new?task={task.id}')
    assert b'Logging whiteboard card' in page.data and b'value="Oil change"' in page.data

    r = client.post(f'/cars/{car.id}/events/new?task={task.id}', data={
        'title': 'Oil change', 'event_type': 'Maintenance', 'provider_type': 'Self',
        'date': TODAY.isoformat(), 'mileage_at_event_unit': 'km',
    })
    assert r.status_code == 302
    db.session.refresh(task)
    assert task.event_id is not None
    items = EventLineItem.query.filter_by(event_id=task.event_id).all()
    assert sorted((i.description, i.unit_cost) for i in items) == [('5W-30 5L', 40), ('Oil filter', 8.5)]
    assert db.session.get(StockItem, filt.id).quantity == 2


def test_line_item_from_shelf_deducts_and_returns(client, db):
    car = make_car()
    event = make_event(car, TODAY, 'Maintenance')
    bulb = StockItem(name='H7 bulb', quantity=2, unit='pcs', unit_cost=6)
    db.session.add(bulb)
    db.session.commit()

    form = {'stock_item_id': bulb.id, 'description': '', 'item_type': 'Parts',
            'quantity': 1, 'unit_cost': 6, 'shipping_cost': 0}
    client.post(f'/events/{event.id}/items/add', data=form)
    item = EventLineItem.query.filter_by(event_id=event.id).one()
    assert item.description == 'H7 bulb' and item.stock_item_id == bulb.id
    assert db.session.get(StockItem, bulb.id).quantity == 1

    # Asking for more than is on the shelf is refused
    client.post(f'/events/{event.id}/items/add', data={**form, 'quantity': 5})
    assert EventLineItem.query.filter_by(event_id=event.id).count() == 1

    client.post(f'/events/{event.id}/items/{item.id}/delete')
    assert db.session.get(StockItem, bulb.id).quantity == 2


def test_deleting_event_returns_stock(client, db):
    car = make_car()
    event = make_event(car, TODAY, 'Maintenance')
    oil = StockItem(name='Oil', quantity=5, unit='L')
    db.session.add(oil)
    db.session.flush()
    db.session.add(EventLineItem(event_id=event.id, description='Oil', quantity=4, unit_cost=0, stock_item_id=oil.id))
    oil.quantity = 1
    db.session.commit()
    client.post(f'/events/{event.id}/delete')
    assert db.session.get(StockItem, oil.id).quantity == 5
