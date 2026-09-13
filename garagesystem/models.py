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
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_modified = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    line_items = db.relationship(
        'EventLineItem', backref='event', lazy=True,
        cascade='all, delete-orphan'
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
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def total(self):
        return round(self.quantity * self.unit_cost + self.shipping_cost, 2)

    def __repr__(self):
        return f'LineItem({self.description} x{self.quantity})'
