from datetime import date

from garagesystem import db
from garagesystem.models import Car, MileageLog, ServiceEvent


def make_car(registration='201D12345', year=2020, **kw):
    car = Car(registration=registration, make='Skoda', model='Octavia', year=year, **kw)
    db.session.add(car)
    db.session.flush()
    return car


def log_mileage(car, when, km):
    db.session.add(MileageLog(car_id=car.id, date=when, mileage=km))
    db.session.flush()


def make_event(car, when, event_type='Service', title=None, mileage=None, **kw):
    e = ServiceEvent(car_id=car.id, date=when, event_type=event_type,
                     title=title or event_type, mileage_at_event=mileage, **kw)
    db.session.add(e)
    db.session.flush()
    return e
