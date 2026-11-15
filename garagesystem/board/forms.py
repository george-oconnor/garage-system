from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, FloatField, SelectField, TextAreaField, DateField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange

PRIORITIES = [('normal', 'Normal'), ('high', 'High'), ('low', 'Low')]
COLOURS = [('yellow', 'Yellow'), ('pink', 'Pink'), ('blue', 'Blue'), ('green', 'Green'), ('orange', 'Orange')]
STATUSES = [('todo', 'To do'), ('parts', 'Waiting on parts'), ('doing', 'In progress'), ('done', 'Done')]
MILEAGE_UNITS = [('km', 'km'), ('mi', 'mi')]


class TaskForm(FlaskForm):
    title = StringField('Job', validators=[DataRequired(), Length(max=200)])
    car_id = SelectField('Car', coerce=int, validators=[Optional()])
    status = SelectField('Column', choices=STATUSES, default='todo')
    priority = SelectField('Priority', choices=PRIORITIES, default='normal')
    colour = SelectField('Sticky note', choices=COLOURS, default='yellow')
    due_date = DateField('Due by date', validators=[Optional()])
    due_mileage = IntegerField('Due by mileage', validators=[Optional(), NumberRange(min=0)])
    due_mileage_unit = SelectField('Unit', choices=MILEAGE_UNITS, default='km')
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save')


class TaskPartForm(FlaskForm):
    description = StringField('Part', validators=[Optional(), Length(max=300)])
    part_number = StringField('Part No.', validators=[Optional(), Length(max=100)])
    quantity = FloatField('Qty', default=1, validators=[DataRequired(), NumberRange(min=0.001)])
    unit_cost = FloatField('Est. cost each (€)', validators=[Optional(), NumberRange(min=0)])
    stock_item_id = SelectField('From the shelf', coerce=int, default=0)
    submit = SubmitField('Add Part')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        if not (self.description.data or '').strip() and not self.stock_item_id.data:
            self.description.errors.append('Describe the part, or pick one from the shelf.')
            return False
        return True
