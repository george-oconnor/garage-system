from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, IntegerField, FloatField, SelectField,
    TextAreaField, DateField, SubmitField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError
from datetime import date as dt_date


class PlateSearchForm(FlaskForm):
    registration = StringField('Registration Number', validators=[DataRequired(), Length(max=20)])
    submit = SubmitField('Look Up Plate')

FUEL_TYPES = [
    ('', 'Select fuel type...'),
    ('Petrol', 'Petrol'),
    ('Diesel', 'Diesel'),
    ('Electric', 'Electric'),
    ('Hybrid Petrol', 'Hybrid Petrol'),
    ('Hybrid Diesel', 'Hybrid Diesel'),
    ('Other', 'Other'),
]

TRANSMISSIONS = [
    ('', 'Select transmission...'),
    ('Manual', 'Manual'),
    ('Automatic', 'Automatic'),
    ('Semi-Automatic', 'Semi-Automatic'),
    ('Other', 'Other'),
]

MILEAGE_UNITS = [
    ('km', 'km'),
    ('mi', 'mi'),
]


class AddCarForm(FlaskForm):
    registration = StringField('Registration', validators=[DataRequired(), Length(max=20)])
    make = StringField('Make', validators=[DataRequired(), Length(max=100)])
    model = StringField('Model', validators=[DataRequired(), Length(max=100)])
    variant = StringField('Variant / Trim', validators=[Optional(), Length(max=200)])
    year = IntegerField('Year', validators=[Optional()])
    color = StringField('Colour', validators=[Optional(), Length(max=50)])
    vin = StringField('VIN', validators=[Optional(), Length(max=50)])
    engine_size = StringField('Engine Size (e.g. 1.6)', validators=[Optional(), Length(max=20)])
    fuel_type = SelectField('Fuel Type', choices=FUEL_TYPES, validators=[Optional()])
    transmission = SelectField('Transmission', choices=TRANSMISSIONS, validators=[Optional()])
    current_mileage = IntegerField('Current Mileage', validators=[Optional()])
    current_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    purchase_date = DateField('Purchase Date', validators=[Optional()])
    purchase_price = FloatField('Purchase Price (€)', validators=[Optional()])
    purchase_mileage = IntegerField('Mileage at Purchase', validators=[Optional()])
    purchase_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Car')

    def validate_registration(self, field):
        from garagesystem.models import Car
        normalized = field.data.upper().strip()
        car = Car.query.filter_by(registration=normalized).first()
        if car:
            raise ValidationError('A car with this registration is already saved.')


class EditCarForm(FlaskForm):
    registration = StringField('Registration', validators=[DataRequired(), Length(max=20)])
    make = StringField('Make', validators=[DataRequired(), Length(max=100)])
    model = StringField('Model', validators=[DataRequired(), Length(max=100)])
    variant = StringField('Variant / Trim', validators=[Optional(), Length(max=200)])
    year = IntegerField('Year', validators=[Optional()])
    color = StringField('Colour', validators=[Optional(), Length(max=50)])
    vin = StringField('VIN', validators=[Optional(), Length(max=50)])
    engine_size = StringField('Engine Size (e.g. 1.6)', validators=[Optional(), Length(max=20)])
    fuel_type = SelectField('Fuel Type', choices=FUEL_TYPES, validators=[Optional()])
    transmission = SelectField('Transmission', choices=TRANSMISSIONS, validators=[Optional()])
    current_mileage = IntegerField('Current Mileage', validators=[Optional()])
    current_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    purchase_date = DateField('Purchase Date', validators=[Optional()])
    purchase_price = FloatField('Purchase Price (€)', validators=[Optional()])
    purchase_mileage = IntegerField('Mileage at Purchase', validators=[Optional()])
    purchase_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    service_interval_km = IntegerField('Service Interval (km)', validators=[Optional(), NumberRange(min=1)])
    service_interval_months = IntegerField('Service Interval (months)', validators=[Optional(), NumberRange(min=1)])
    notes = TextAreaField('Notes', validators=[Optional()])
    image = FileField('Photo', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only')])
    submit = SubmitField('Update Car')


class AddMileageForm(FlaskForm):
    mileage = IntegerField('Mileage', validators=[DataRequired()])
    mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    date = DateField('Date', validators=[DataRequired()], default=dt_date.today)
    notes = StringField('Notes', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Log Mileage')
