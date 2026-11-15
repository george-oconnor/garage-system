from garagesystem import db, login_manager
from flask_login import UserMixin
from datetime import datetime, date


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'User({self.username})'

    def get_reset_token(self, expires_sec=1800):
        from flask import current_app
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        return s.dumps(self.id, salt='password-reset')

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        from flask import current_app
        from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, salt='password-reset', max_age=expires_sec)
        except (BadSignature, SignatureExpired):
            return None
        return db.session.get(User, user_id)


class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(20), unique=True, nullable=False)
    make = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    variant = db.Column(db.String(200), nullable=True)   # full trim/variant description from lookup
    year = db.Column(db.Integer, nullable=True)
    color = db.Column(db.String(50), nullable=True)
    vin = db.Column(db.String(50), nullable=True)
    engine_size = db.Column(db.String(20), nullable=True)
    fuel_type = db.Column(db.String(20), nullable=True)
    transmission = db.Column(db.String(20), nullable=True)
    current_mileage = db.Column(db.Integer, nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    purchase_price = db.Column(db.Float, nullable=True)
    purchase_mileage = db.Column(db.Integer, nullable=True)
    # Assumed service schedule, used to project the next service due date/mileage
    # on the Insights panel. Defaults to a common manufacturer-agnostic interval.
    service_interval_km = db.Column(db.Integer, nullable=True, default=10000, server_default='10000')
    service_interval_months = db.Column(db.Integer, nullable=True, default=12, server_default='12')
    notes = db.Column(db.Text, nullable=True)
    lookup_data = db.Column(db.Text, nullable=True)      # raw JSON from vehicle lookup API
    image_url = db.Column(db.Text, nullable=True)        # thumbnail URL from Wikimedia Commons
    image_custom = db.Column(db.String(200), nullable=True)  # user-uploaded image filename
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_modified = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    mileage_logs = db.relationship(
        'MileageLog', backref='car', lazy=True,
        cascade='all, delete-orphan'
    )
    service_events = db.relationship(
        'ServiceEvent', backref='car', lazy=True,
        cascade='all, delete-orphan'
    )
    fuel_logs = db.relationship(
        'FuelLog', backref='car', lazy=True,
        cascade='all, delete-orphan'
    )
    schedule_items = db.relationship(
        'MaintenanceSchedule', backref='car', lazy=True,
        cascade='all, delete-orphan', order_by='MaintenanceSchedule.name'
    )
    tasks = db.relationship(
        'Task', backref='car', lazy=True,
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'{self.registration} - {self.make} {self.model}'

    @property
    def ordered_events(self):
        return sorted(self.service_events, key=lambda e: e.date, reverse=True)

    @property
    def ordered_mileage(self):
        return sorted(self.mileage_logs, key=lambda l: l.date, reverse=True)

    @property
    def total_service_spend(self):
        return round(sum(e.total_cost for e in self.service_events), 2)

    @property
    def event_count(self):
        return len(self.service_events)

    @property
    def ordered_fuel_logs(self):
        return sorted(self.fuel_logs, key=lambda f: (f.date, f.mileage or 0), reverse=True)

    @property
    def total_fuel_spend(self):
        return round(sum(f.total_cost or 0 for f in self.fuel_logs), 2)

    @property
    def open_tasks(self):
        return [t for t in self.tasks if t.is_open]

    @property
    def latest_mileage(self):
        if self.mileage_logs:
            return max(l.mileage for l in self.mileage_logs)
        return self.current_mileage


class MileageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    mileage = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.String(300), nullable=True)
    # When this log was auto-created from a ServiceEvent, this points back to that event
    # so edits/deletes on the event stay in sync with the log.
    source_event_id = db.Column(
        db.Integer,
        db.ForeignKey('service_event.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Marks the single auto-created log representing the car's purchase_mileage/
    # purchase_date, so it can be kept in sync the same way source_event_id keeps
    # an event's mileage log in sync.
    is_purchase_mileage = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # When this log was auto-created from a FuelLog fill-up, this points back to it.
    source_fuel_id = db.Column(
        db.Integer,
        db.ForeignKey('fuel_log.id', ondelete='SET NULL'),
        nullable=True,
    )
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'MileageLog({self.mileage} on {self.date})'


class ServiceEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    event_type = db.Column(db.String(50), nullable=False, default='Maintenance')
    date = db.Column(db.Date, nullable=False, default=date.today)
    mileage_at_event = db.Column(db.Integer, nullable=True)
    garage_name = db.Column(db.String(200), nullable=True)
    garage_address = db.Column(db.String(300), nullable=True)
    invoice_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # Who did the work: 'Self' (owner did it) or 'ThirdParty' (a garage / provider)
    provider_type = db.Column(db.String(20), nullable=False, default='Self', server_default='Self')
    # Third-party only: uploaded invoice PDF and manually-entered total cost
    invoice_filename = db.Column(db.String(200), nullable=True)
    total_cost_override = db.Column(db.Float, nullable=True)
    # NCT-specific fields (only meaningful when event_type == 'NCT')
    nct_result = db.Column(db.String(10), nullable=True)          # 'Pass' or 'Fail'
    nct_cert_filename = db.Column(db.String(200), nullable=True)  # uploaded PDF filename
    # Manual override for the next NCT due date (Pass results only) — takes
    # priority over the estimate derived from Irish NCT interval rules.
    nct_next_due = db.Column(db.Date, nullable=True)
    # Tax / Insurance only: the date the motor tax disc or insurance policy
    # paid for by this event runs out. Drives the renewal reminders.
    expiry_date = db.Column(db.Date, nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_modified = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    line_items = db.relationship(
        'EventLineItem', backref='event', lazy=True,
        cascade='all, delete-orphan'
    )
    # Maintenance schedule items (timing belt, brake fluid, ...) this event
    # carried out. The latest linked event resets that item's due date.
    schedule_items = db.relationship(
        'MaintenanceSchedule', secondary='event_schedule_link',
        backref=db.backref('events', lazy=True), lazy=True,
    )

    @property
    def total_cost(self):
        # Third-party events use the invoice's total cost directly (no line items).
        if self.total_cost_override is not None:
            return round(self.total_cost_override, 2)
        return round(sum(item.total for item in self.line_items), 2)

    @property
    def uses_invoice(self):
        """True when this event's cost is captured via an uploaded invoice PDF."""
        return self.provider_type == 'ThirdParty' and bool(self.invoice_filename)

    @property
    def labour_cost(self):
        # Excludes shipping, which is broken out separately via shipping_cost.
        return round(sum(item.quantity * item.unit_cost for item in self.line_items if item.item_type == 'Labour'), 2)

    @property
    def parts_cost(self):
        # Excludes shipping, which is broken out separately via shipping_cost.
        return round(sum(item.quantity * item.unit_cost for item in self.line_items
                         if item.item_type in ('Parts', 'Consumables')), 2)

    @property
    def shipping_cost(self):
        return round(sum(item.shipping_cost for item in self.line_items), 2)

    def __repr__(self):
        return f'ServiceEvent({self.title} on {self.date})'


class EventLineItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('service_event.id'), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    item_type = db.Column(db.String(50), nullable=False, default='Parts')
    part_number = db.Column(db.String(100), nullable=True)
    quantity = db.Column(db.Float, nullable=False, default=1.0)
    unit_cost = db.Column(db.Float, nullable=False, default=0.0)
    shipping_cost = db.Column(db.Float, nullable=False, default=0.0, server_default='0')
    # Set when this item was taken from the shelf: its quantity was deducted
    # from that stock item, and is returned if the line item is removed.
    stock_item_id = db.Column(
        db.Integer,
        db.ForeignKey('stock_item.id', ondelete='SET NULL'),
        nullable=True,
    )
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    stock_item = db.relationship('StockItem', lazy=True)

    @property
    def total(self):
        return round(self.quantity * self.unit_cost + self.shipping_cost, 2)

    def __repr__(self):
        return f'LineItem({self.description} x{self.quantity})'


event_schedule_link = db.Table(
    'event_schedule_link',
    db.Column('event_id', db.Integer, db.ForeignKey('service_event.id', ondelete='CASCADE'), primary_key=True),
    db.Column('schedule_id', db.Integer, db.ForeignKey('maintenance_schedule.id', ondelete='CASCADE'), primary_key=True),
)


class MaintenanceSchedule(db.Model):
    """A recurring maintenance item for one car, e.g. "Timing belt every
    100,000 km or 5 years". Either interval may be blank; whichever comes
    first sets the due date."""
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    interval_km = db.Column(db.Integer, nullable=True)
    interval_months = db.Column(db.Integer, nullable=True)
    # When it was last done before it was tracked here. A linked event that is
    # more recent takes priority.
    last_done_date = db.Column(db.Date, nullable=True)
    last_done_mileage = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.String(300), nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'MaintenanceSchedule({self.name})'


class FuelLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    mileage = db.Column(db.Integer, nullable=True)          # odometer, km
    litres = db.Column(db.Float, nullable=False)             # litres (kWh for EVs)
    total_cost = db.Column(db.Float, nullable=True)
    # Economy is measured full-tank to full-tank, so partial fills are summed
    # into the next full one.
    full_tank = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    station = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.String(300), nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def price_per_litre(self):
        if self.total_cost and self.litres:
            return round(self.total_cost / self.litres, 3)
        return None

    def __repr__(self):
        return f'FuelLog({self.litres}L on {self.date})'


class StockItem(db.Model):
    """Something on the garage shelf: oil, filters, bulbs, fluids."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='Other')
    part_number = db.Column(db.String(100), nullable=True)
    quantity = db.Column(db.Float, nullable=False, default=0, server_default='0')
    unit = db.Column(db.String(20), nullable=False, default='pcs', server_default='pcs')
    unit_cost = db.Column(db.Float, nullable=True)
    # At or below this quantity the item is "low" and a restock card goes on
    # the whiteboard.
    min_quantity = db.Column(db.Float, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    fits = db.Column(db.String(200), nullable=True)     # e.g. "Golf, Octavia"
    notes = db.Column(db.String(300), nullable=True)
    # Bumped whenever the quantity goes up, so a new low-stock card can be
    # raised after the previous one was dealt with.
    last_restocked = db.Column(db.DateTime, nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def is_low(self):
        return self.min_quantity is not None and self.quantity <= self.min_quantity

    def __repr__(self):
        return f'StockItem({self.name} x{self.quantity})'


TASK_STATUSES = ('todo', 'parts', 'doing', 'done')


class Task(db.Model):
    """A card on the garage whiteboard."""
    id = db.Column(db.Integer, primary_key=True)
    # Blank for garage-wide jobs ("buy axle stands").
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    # todo | parts | doing | done | dismissed (an auto card that was binned)
    status = db.Column(db.String(20), nullable=False, default='todo', server_default='todo')
    priority = db.Column(db.String(10), nullable=False, default='normal', server_default='normal')
    colour = db.Column(db.String(20), nullable=False, default='yellow', server_default='yellow')
    due_date = db.Column(db.Date, nullable=True)
    due_mileage = db.Column(db.Integer, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # Cards raised automatically: 'schedule', 'service', 'nct', 'tax',
    # 'insurance' or 'stock'. source_key identifies the thing that's due and
    # its cycle, so a card is raised once per cycle (see board.utils).
    source = db.Column(db.String(20), nullable=False, default='manual', server_default='manual')
    source_key = db.Column(db.String(120), nullable=True, index=True)
    schedule_id = db.Column(
        db.Integer, db.ForeignKey('maintenance_schedule.id', ondelete='SET NULL'), nullable=True)
    stock_item_id = db.Column(
        db.Integer, db.ForeignKey('stock_item.id', ondelete='SET NULL'), nullable=True)
    # The service event logged when this card was completed.
    event_id = db.Column(
        db.Integer, db.ForeignKey('service_event.id', ondelete='SET NULL'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    parts = db.relationship(
        'TaskPart', backref='task', lazy=True,
        cascade='all, delete-orphan', order_by='TaskPart.id'
    )
    schedule_item = db.relationship('MaintenanceSchedule', lazy=True)
    stock_item = db.relationship('StockItem', lazy=True)
    event = db.relationship('ServiceEvent', lazy=True)

    @property
    def is_open(self):
        return self.status in ('todo', 'parts', 'doing')

    @property
    def is_auto(self):
        return self.source != 'manual'

    def __repr__(self):
        return f'Task({self.title} [{self.status}])'


PART_STATUSES = ('needed', 'ordered', 'arrived')


class TaskPart(db.Model):
    """A part a whiteboard job needs. Becomes a line item when the job is
    logged as a service event."""
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    part_number = db.Column(db.String(100), nullable=True)
    quantity = db.Column(db.Float, nullable=False, default=1.0)
    unit_cost = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='needed', server_default='needed')
    # Take it from the shelf instead of buying it.
    stock_item_id = db.Column(
        db.Integer, db.ForeignKey('stock_item.id', ondelete='SET NULL'), nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    stock_item = db.relationship('StockItem', lazy=True)

    def __repr__(self):
        return f'TaskPart({self.description})'
