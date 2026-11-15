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


def test_tick_off_offers_to_log_and_can_be_undone(client, db):
    car = make_car()
    job = Task(title='Fix boot rattle', car_id=car.id, status='doing')
    garage = Task(title='Buy axle stands', status='todo')
    db.session.add_all([job, garage])
    db.session.commit()

    r = client.post(f'/board/tasks/{job.id}/done')
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/board?done={job.id}')
    db.session.refresh(job)
    assert job.status == 'done' and job.completed_at is not None
    page = client.get(f'/board?done={job.id}').get_data(as_text=True)
    assert 'Log service event' in page and 'Done lately' in page

    # A garage job (no car) isn't offered for logging
    client.post(f'/board/tasks/{garage.id}/done')
    assert 'Log service event' not in client.get(f'/board?done={garage.id}').get_data(as_text=True)

    client.post(f'/board/tasks/{job.id}/reopen')
    db.session.refresh(job)
    assert job.status == 'todo' and job.completed_at is None


def test_list_puts_overdue_first(client, db):
    car = make_car(year=TODAY.year)
    db.session.add_all([
        Task(title='Later job', car_id=car.id, due_date=TODAY + timedelta(days=90)),
        Task(title='Overdue job', car_id=car.id, due_date=TODAY - timedelta(days=1)),
        Task(title='No date job'),
    ])
    db.session.commit()
    page = client.get('/board').get_data(as_text=True)
    assert page.index('Overdue job') < page.index('Later job') < page.index('No date job')


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


def test_service_item_raises_one_service_card(db):
    car = make_car(year=TODAY.year)
    item = MaintenanceSchedule(car_id=car.id, name='Service', interval_months=12, is_service=True,
                               last_done_date=TODAY - timedelta(days=360))
    db.session.add(item)
    db.session.commit()

    sync_auto_tasks()
    cards = Task.query.filter(Task.car_id == car.id).all()
    assert [(c.source, c.title, c.schedule_id) for c in cards] == [('service', 'Service due', item.id)]

    # Logging a Service event moves it on to the next cycle and closes the card
    make_event(car, TODAY, 'Service')
    db.session.commit()
    sync_auto_tasks()
    db.session.refresh(cards[0])
    assert cards[0].status == 'done'


def test_service_item_cannot_be_removed(client, db):
    car = make_car()
    item = MaintenanceSchedule(car_id=car.id, name='Service', interval_km=10000, is_service=True)
    db.session.add(item)
    db.session.commit()
    client.post(f'/cars/{car.id}/schedule/{item.id}/delete')
    assert db.session.get(MaintenanceSchedule, item.id) is not None
