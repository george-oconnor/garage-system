from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SelectField, SubmitField
from wtforms.validators import DataRequired, InputRequired, Optional, Length, NumberRange

STOCK_CATEGORIES = [
    ('Oil', 'Oil'),
    ('Filters', 'Filters'),
    ('Bulbs', 'Bulbs'),
    ('Fluids', 'Fluids'),
    ('Brakes', 'Brakes'),
    ('Wipers', 'Wipers'),
    ('Fixings', 'Fixings'),
    ('Other', 'Other'),
]

STOCK_UNITS = [('pcs', 'pcs'), ('L', 'L'), ('ml', 'ml'), ('kg', 'kg'), ('set', 'set'), ('pair', 'pair')]


class StockItemForm(FlaskForm):
    name = StringField('Item', validators=[DataRequired(), Length(max=200)])
    category = SelectField('Category', choices=STOCK_CATEGORIES, default='Other')
    part_number = StringField('Part No.', validators=[Optional(), Length(max=100)])
    quantity = FloatField('On the shelf', default=1, validators=[InputRequired(message='Enter how many you have (0 is fine).'), NumberRange(min=0)])
    unit = SelectField('Unit', choices=STOCK_UNITS, default='pcs')
    unit_cost = FloatField('Cost each (€)', validators=[Optional(), NumberRange(min=0)])
    min_quantity = FloatField('Restock at', validators=[Optional(), NumberRange(min=0)])
    location = StringField('Where it is', validators=[Optional(), Length(max=100)])
    fits = StringField('Fits', validators=[Optional(), Length(max=200)])
    notes = StringField('Notes', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Save')

