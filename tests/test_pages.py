"""Every new page renders, and the main flows work end to end."""
from datetime import date, timedelta
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from garagesystem.models import FuelLog, MaintenanceSchedule, MileageLog, StockItem, Task
from tests.factories import make_car, make_event, log_mileage

TODAY = date.today()


def _populated(db):
    car = make_car(purchase_date=TODAY - timedelta(days=900), purchase_mileage=30000)
    log_mileage(car, TODAY - timedelta(days=400), 40000)
    log_mileage(car, TODAY, 52000)
    svc = make_event(car, TODAY - timedelta(days=380), 'Service', mileage=41000)
    make_event(car, TODAY - timedelta(days=200), 'NCT', nct_result='Pass', garage_name='Deansgrange')
    make_event(car, TODAY - timedelta(days=350), 'Insurance', expiry_date=TODAY + timedelta(days=15))
    item = MaintenanceSchedule(car_id=car.id, name='Timing belt', interval_km=100000, interval_months=60,
                               last_done_date=TODAY - timedelta(days=1700), last_done_mileage=0)
    db.session.add(item)
    svc.schedule_items.append(item)
    db.session.add(FuelLog(car_id=car.id, date=TODAY - timedelta(days=20), mileage=51000, litres=45, total_cost=80))
    db.session.add(FuelLog(car_id=car.id, date=TODAY, mileage=51700, litres=40, total_cost=72))
    db.session.add(StockItem(name='Oil filter', quantity=0, min_quantity=1))
    db.session.add(Task(title='Fix boot rattle', car_id=car.id, status='doing'))
    db.session.add(Task(title='Buy axle stands', status='todo', colour='orange', priority='high'))
    db.session.commit()
    return car


def test_pages_render(client, db):
    car = _populated(db)
    for url in ('/', '/board', '/shelf', f'/cars/{car.id}', f'/cars/{car.id}/events/new',
                f'/cars/{car.id}/schedule/{car.schedule_items[0].id}/edit',
                f'/events/{car.service_events[0].id}', f'/events/{car.service_events[0].id}/edit'):
        r = client.get(url)
        assert r.status_code == 200, url

    task = Task.query.first()
    assert client.get(f'/board/tasks/{task.id}').status_code == 200
    stock = StockItem.query.first()
    assert client.get(f'/shelf/{stock.id}/edit').status_code == 200

    board = client.get('/board').get_data(as_text=True)
    assert 'Insurance renewal' in board        # due in 15 days -> auto card
    assert 'Restock Oil filter' in board
    assert 'Fix boot rattle' in board

    page = client.get(f'/cars/{car.id}').get_data(as_text=True)
    assert 'id="schedule"' in page and 'Timing belt' in page
    assert 'id="fuel"' in page and 'Log fill-up' in page and 'L/100km' in page


def test_fuel_log_feeds_mileage_log(client, db):
    car = make_car()
    db.session.commit()
    client.post(f'/cars/{car.id}/fuel/add', data={
        'date': TODAY.isoformat(), 'mileage': 60000, 'mileage_unit': 'km',
        'litres': 40, 'total_cost': 70, 'full_tank': 'y',
    })
    fuel = FuelLog.query.one()
    assert MileageLog.query.filter_by(source_fuel_id=fuel.id).one().mileage == 60000
    assert car.current_mileage == 60000
    client.post(f'/cars/{car.id}/fuel/{fuel.id}/delete')
    assert MileageLog.query.count() == 0


def test_schedule_presets_and_event_link(client, db):
    car = make_car()
    db.session.commit()
    client.post(f'/cars/{car.id}/schedule/presets', data={'preset': ['Brake fluid', 'Spark plugs']})
    names = sorted(i.name for i in car.schedule_items)
    assert names == ['Brake fluid', 'Spark plugs']
    # Adding the same preset again doesn't duplicate it
    client.post(f'/cars/{car.id}/schedule/presets', data={'preset': ['Brake fluid']})
    assert len(car.schedule_items) == 2

    fluid = next(i for i in car.schedule_items if i.name == 'Brake fluid')
    client.post(f'/cars/{car.id}/events/new', data={
        'title': 'Brake fluid flush', 'event_type': 'Maintenance', 'provider_type': 'Self',
        'date': TODAY.isoformat(), 'mileage_at_event_unit': 'km', 'schedule_items': [fluid.id],
    })
    assert [e.title for e in fluid.events] == ['Brake fluid flush']


def test_tax_event_saves_expiry(client, db):
    car = make_car()
    db.session.commit()
    client.post(f'/cars/{car.id}/events/new', data={
        'title': 'Motor tax', 'event_type': 'Tax', 'provider_type': 'Self',
        'date': TODAY.isoformat(), 'mileage_at_event_unit': 'km',
        'expiry_date': (TODAY + timedelta(days=365)).isoformat(),
    })
    assert car.service_events[0].expiry_date == TODAY + timedelta(days=365)


def test_history_pdf_appends_nct_cert(client, db, app, tmp_path, monkeypatch):
    import os
    car = _populated(db)
    nct = next(e for e in car.service_events if e.event_type == 'NCT')

    # A one-page "certificate" in a temporary static folder
    static = tmp_path / 'static'
    (static / 'nct_certs').mkdir(parents=True)
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(static / 'nct_certs' / 'cert.pdf', 'wb') as f:
        w.write(f)
    nct.nct_cert_filename = 'cert.pdf'
    db.session.commit()
    # Point the app's static folder lookup at the temporary one
    real_join = os.path.join
    monkeypatch.setattr('garagesystem.upkeep.history.os.path.join',
                        lambda *p: real_join(str(tmp_path), *p[1:]) if p[1:2] == ('static',) else real_join(*p))

    r = client.get(f'/cars/{car.id}/history.pdf')
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    with_cert = PdfReader(BytesIO(r.data))
    outline = [o.title for o in with_cert.outline]
    assert outline[0] == 'Service history' and outline[1].startswith('NCT certificate')

    r = client.get(f'/cars/{car.id}/history.pdf?costs=0&certs=0&invoices=0')
    without = PdfReader(BytesIO(r.data))
    assert len(without.pages) == len(with_cert.pages) - 1
    assert '€' not in without.pages[0].extract_text()


def test_new_car_gets_a_service_item(client, db, app):
    with client.session_transaction(base_url='https://localhost') as sess:
        sess['new_car_prefill'] = {'registration': '242D555', 'make': 'Ford', 'model': 'Focus'}
    client.post('/cars/new/details', base_url='https://localhost', data={
        'registration': '242D555', 'make': 'Ford', 'model': 'Focus',
        'current_mileage_unit': 'km', 'purchase_mileage_unit': 'km',
    })
    from garagesystem.models import Car
    car = Car.query.filter_by(registration='242D555').one()
    assert [(i.name, i.interval_km, i.interval_months, i.is_service) for i in car.schedule_items] == [
        ('Service', 10000, 12, True)]


def test_car_page_mini_board_is_read_only(client, db):
    car = _populated(db)
    page = client.get(f'/cars/{car.id}').get_data(as_text=True)
    mini = page[page.index('id="miniBoardTitle"'):page.index('id="records"')]
    assert 'Fix boot rattle' in mini and 'Buy axle stands' not in mini   # only this car's jobs
    assert 'wb-check' not in mini                                       # no tick boxes
    assert f'/board?show={car.id}' in mini
