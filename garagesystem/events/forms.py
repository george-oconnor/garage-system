from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, IntegerField, FloatField, SelectField,
    TextAreaField, DateField, SubmitField, BooleanField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange
from datetime import date as dt_date

EVENT_TYPES = [
    ('Service', 'Service'),
    ('Repair', 'Repair'),
    ('Maintenance', 'Maintenance'),
    ('NCT', 'NCT'),
    ('Tax', 'Tax'),
    ('Insurance', 'Insurance'),
    ('Inspection', 'Inspection'),
    ('Modification', 'Modification'),
    ('Purchase', 'Purchase'),
    ('Other', 'Other'),
]

ITEM_TYPES = [
    ('Parts', 'Parts'),
    ('Labour', 'Labour'),
    ('Consumables', 'Consumables'),
    ('Other', 'Other'),
]

NCT_RESULTS = [
    ('', '— Select result —'),
    ('Pass', 'Pass'),
    ('Fail', 'Fail'),
]

PROVIDER_TYPES = [
    ('Self', 'Self — I did this work'),
    ('ThirdParty', 'Third-party garage / provider'),
]

MILEAGE_UNITS = [
    ('km', 'km'),
    ('mi', 'mi'),
]


class AddEventForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    event_type = SelectField('Event Type', choices=EVENT_TYPES, validators=[DataRequired()])
    provider_type = SelectField('Who did the work?', choices=PROVIDER_TYPES,
                                validators=[DataRequired()], default='Self')
    date = DateField('Date', validators=[DataRequired()], default=dt_date.today)
    mileage_at_event = IntegerField('Mileage at Event', validators=[Optional()])
    mileage_at_event_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    garage_name = StringField('Garage / Provider', validators=[Optional(), Length(max=200)])
    garage_address = StringField('Address', validators=[Optional(), Length(max=300)])
    invoice_number = StringField('Invoice / Reference No.', validators=[Optional(), Length(max=100)])
    notes = TextAreaField('Notes', validators=[Optional()])
    # Third-party only: upload invoice PDF and its total cost (instead of manual line items)
    invoice_pdf = FileField('Invoice PDF',
                            validators=[Optional(), FileAllowed(['pdf'], 'PDF files only.')])
    total_cost_override = FloatField('Total Cost (€)',
                                     validators=[Optional(), NumberRange(min=0)])
    # NCT-specific
    nct_result = SelectField('NCT Result', choices=NCT_RESULTS, validators=[Optional()])
    nct_cert = FileField('NCT Certificate (PDF)',
                         validators=[Optional(), FileAllowed(['pdf'], 'PDF files only.')])
    submit = SubmitField('Save Event')


class EditEventForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    event_type = SelectField('Event Type', choices=EVENT_TYPES, validators=[DataRequired()])
    provider_type = SelectField('Who did the work?', choices=PROVIDER_TYPES,
                                validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()])
    mileage_at_event = IntegerField('Mileage at Event', validators=[Optional()])
    mileage_at_event_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km', validators=[Optional()])
    garage_name = StringField('Garage / Provider', validators=[Optional(), Length(max=200)])
    garage_address = StringField('Address', validators=[Optional(), Length(max=300)])
    invoice_number = StringField('Invoice / Reference No.', validators=[Optional(), Length(max=100)])
    notes = TextAreaField('Notes', validators=[Optional()])
    # Third-party only
    invoice_pdf = FileField('Replace Invoice PDF',
                            validators=[Optional(), FileAllowed(['pdf'], 'PDF files only.')])
    remove_invoice = BooleanField('Remove existing invoice PDF')
    total_cost_override = FloatField('Total Cost (€)',
                                     validators=[Optional(), NumberRange(min=0)])
    # NCT-specific
    nct_result = SelectField('NCT Result', choices=NCT_RESULTS, validators=[Optional()])
    nct_cert = FileField('Replace NCT Certificate (PDF)',
                         validators=[Optional(), FileAllowed(['pdf'], 'PDF files only.')])
    remove_nct_cert = BooleanField('Remove existing certificate')
    submit = SubmitField('Update Event')


class AddLineItemForm(FlaskForm):
    description = StringField('Description', validators=[DataRequired(), Length(max=300)])
    item_type = SelectField('Type', choices=ITEM_TYPES, validators=[DataRequired()])
    part_number = StringField('Part No.', validators=[Optional(), Length(max=100)])
    quantity = FloatField('Qty', validators=[DataRequired(), NumberRange(min=0.001)])
    unit_cost = FloatField('Unit Cost (€)', validators=[DataRequired(), NumberRange(min=0)])
    shipping_cost = FloatField('Shipping (€)', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Add Item')
