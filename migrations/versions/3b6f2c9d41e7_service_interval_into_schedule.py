"""Move each car's service interval into a "Service" maintenance schedule item

Revision ID: 3b6f2c9d41e7
Revises: 8e78079d246c
Create Date: 2026-11-15 14:00:00

The service interval used to live on the car (service_interval_km/_months).
It now lives on a MaintenanceSchedule row with is_service = 1, one per car,
so the schedule, Next Service Due and the whiteboard all read from one place.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3b6f2c9d41e7'
down_revision = '8e78079d246c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('maintenance_schedule', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_service', sa.Boolean(), server_default='0', nullable=False))

    # One Service item per car, carrying over its interval (or the old defaults).
    conn = op.get_bind()
    now = datetime.utcnow()
    cars = conn.execute(sa.text('SELECT id, service_interval_km, service_interval_months FROM car')).fetchall()
    for car_id, km, months in cars:
        conn.execute(
            sa.text(
                'INSERT INTO maintenance_schedule (car_id, name, interval_km, interval_months, is_service, date_added) '
                'VALUES (:car_id, :name, :km, :months, 1, :now)'
            ),
            {'car_id': car_id, 'name': 'Service', 'km': km, 'months': months, 'now': now},
        )

    with op.batch_alter_table('car', schema=None) as batch_op:
        batch_op.drop_column('service_interval_months')
        batch_op.drop_column('service_interval_km')


def downgrade():
    with op.batch_alter_table('car', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_interval_km', sa.Integer(), server_default='10000', nullable=True))
        batch_op.add_column(sa.Column('service_interval_months', sa.Integer(), server_default='12', nullable=True))

    # Copy the intervals back to the car, then remove the Service items.
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        'SELECT id, car_id, interval_km, interval_months FROM maintenance_schedule WHERE is_service = 1'
    )).fetchall()
    for item_id, car_id, km, months in rows:
        conn.execute(
            sa.text('UPDATE car SET service_interval_km = :km, service_interval_months = :months WHERE id = :car_id'),
            {'km': km, 'months': months, 'car_id': car_id},
        )
        conn.execute(sa.text('DELETE FROM event_schedule_link WHERE schedule_id = :id'), {'id': item_id})
        conn.execute(sa.text('UPDATE task SET schedule_id = NULL WHERE schedule_id = :id'), {'id': item_id})
        conn.execute(sa.text('DELETE FROM maintenance_schedule WHERE id = :id'), {'id': item_id})

    with op.batch_alter_table('maintenance_schedule', schema=None) as batch_op:
        batch_op.drop_column('is_service')
