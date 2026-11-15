from datetime import date as dt_date

from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, FloatField, SelectField, DateField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange

MILEAGE_UNITS = [('km', 'km'), ('mi', 'mi')]

# Typical intervals, as a starting point. Every car differs, so they can be
# edited after adding. (name, km, months, note)
SCHEDULE_PRESETS = [
    ('Engine oil & filter', 15000, 12, None),
    ('Air filter', 30000, 24, None),
    ('Cabin (pollen) filter', 15000, 12, None),
    ('Fuel filter', 60000, 48, 'Mostly diesels'),
    ('Spark plugs', 60000, 48, 'Petrol engines'),
    ('Timing belt & water pump', 100000, 60, 'Skip if the engine has a timing chain'),
    ('Auxiliary (drive) belt', 100000, 60, None),
    ('Brake fluid', None, 24, None),
    ('Coolant', 100000, 60, None),
    ('Gearbox oil', 100000, 72, None),
    ('Brake pads & discs check', 20000, 12, None),
    ('Tyre rotation & check', 10000, 12, None),
    ('Wiper blades', None, 12, None),
    ('Air con regas', None, 24, None),
]


class FuelLogForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()], default=dt_date.today)
    mileage = IntegerField('Odometer', validators=[Optional(), NumberRange(min=0)])
    mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km')
    litres = FloatField('Litres', validators=[DataRequired(), NumberRange(min=0.01)])
    total_cost = FloatField('Total cost (€)', validators=[Optional(), NumberRange(min=0)])
    full_tank = BooleanField('Filled to full', default=True)
    station = StringField('Station', validators=[Optional(), Length(max=120)])
    notes = StringField('Notes', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Log Fill-up')


class ScheduleForm(FlaskForm):
    name = StringField('Item', validators=[DataRequired(), Length(max=100)])
    interval_km = IntegerField('Every (km)', validators=[Optional(), NumberRange(min=1)])
    interval_months = IntegerField('Every (months)', validators=[Optional(), NumberRange(min=1)])
    last_done_date = DateField('Last done (date)', validators=[Optional()])
    last_done_mileage = IntegerField('Last done (mileage)', validators=[Optional(), NumberRange(min=0)])
    last_done_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km')
    notes = StringField('Notes', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Save')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        if not self.interval_km.data and not self.interval_months.data:
            self.interval_km.errors.append('Give a distance, a time, or both.')
            return False
        return True
