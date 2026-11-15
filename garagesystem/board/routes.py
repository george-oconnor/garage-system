from datetime import datetime, date as _date

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required
from garagesystem.csrf import check_post_csrf

from garagesystem import db
from garagesystem.models import Car, Task, TaskPart, StockItem, TASK_STATUSES, PART_STATUSES
from garagesystem.board.forms import TaskForm, TaskPartForm
from garagesystem.board.utils import sync_auto_tasks, task_urgency, _next_position
from garagesystem.cars.utils import convert_mileage_to_km

board = Blueprint('board', __name__)

# Done cards stay on the board this long, then they're "wiped off".
DONE_VISIBLE_DAYS = 14


board.before_request(check_post_csrf)


def _car_choices():
    cars = Car.query.order_by(Car.registration).all()
    return [(0, '— Garage (no car) —')] + [(c.id, f'{c.registration} · {c.make} {c.model}') for c in cars]


def _stock_choices():
    items = StockItem.query.order_by(StockItem.category, StockItem.name).all()
    return [(0, '— Buy it —')] + [
        (s.id, f'{s.name} ({s.quantity:g} {s.unit} on shelf)') for s in items
    ]


@board.route('/board')
@login_required
def view_board():
    sync_auto_tasks()
    open_tasks = (Task.query.filter(Task.status.in_(('todo', 'parts', 'doing')))
                  .order_by(Task.position, Task.id).all())
    cutoff = datetime.utcnow().timestamp() - DONE_VISIBLE_DAYS * 86400
    done = [t for t in Task.query.filter_by(status='done').order_by(Task.completed_at.desc()).all()
            if t.completed_at and t.completed_at.timestamp() >= cutoff]

    columns = {s: [] for s in TASK_STATUSES}
    for t in open_tasks:
        columns[t.status].append(t)
    columns['done'] = done

    form = TaskForm()
    form.car_id.choices = _car_choices()
    if request.args.get('car', type=int):
        form.car_id.data = request.args.get('car', type=int)
    today = _date.today()
    urgency = {t.id: task_urgency(t, today) for t in open_tasks}
    cars = Car.query.order_by(Car.registration).all()
    return render_template('board/board.html', title='Whiteboard', columns=columns,
                           form=form, urgency=urgency, cars=cars, today=today,
                           overdue_count=sum(1 for u in urgency.values() if u == 'overdue'))


@board.route('/board/tasks/new', methods=['POST'])
@login_required
def add_task():
    form = TaskForm()
    form.car_id.choices = _car_choices()
    if form.validate_on_submit():
        task = Task(
            title=form.title.data.strip(),
            car_id=form.car_id.data or None,
            status=form.status.data,
            priority=form.priority.data,
            colour=form.colour.data,
            due_date=form.due_date.data,
            due_mileage=convert_mileage_to_km(form.due_mileage.data, form.due_mileage_unit.data),
            notes=form.notes.data or None,
            position=_next_position(form.status.data),
        )
        if task.status == 'done':
            task.completed_at = datetime.utcnow()
        db.session.add(task)
        db.session.commit()
        flash(f'"{task.title}" is on the board.', 'success')
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, 'danger')
    return redirect(request.form.get('next') or url_for('board.view_board'))


@board.route('/board/tasks/<int:task_id>', methods=['GET', 'POST'])
@login_required
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    form = TaskForm(obj=task)
    form.car_id.choices = _car_choices()
    if request.method == 'GET':
        form.car_id.data = task.car_id or 0
        if task.status not in TASK_STATUSES:
            form.status.data = 'done'
    part_form = TaskPartForm(prefix='part')
    part_form.stock_item_id.choices = _stock_choices()

    if form.submit.data and form.validate_on_submit():
        new_status = form.status.data
        if new_status != task.status:
            _set_status(task, new_status)
        task.title = form.title.data.strip()
        task.car_id = form.car_id.data or None
        task.priority = form.priority.data
        task.colour = form.colour.data
        task.due_date = form.due_date.data
        task.due_mileage = convert_mileage_to_km(form.due_mileage.data, form.due_mileage_unit.data)
        task.notes = form.notes.data or None
        db.session.commit()
        flash('Card updated.', 'success')
        return redirect(url_for('board.view_task', task_id=task.id))

    return render_template('board/task.html', title=task.title, task=task, form=form,
                           part_form=part_form, urgency=task_urgency(task), part_statuses=PART_STATUSES)


def _set_status(task, status):
    if status == task.status:
        return
    task.status = status
    task.position = _next_position(status)
    task.completed_at = datetime.utcnow() if status == 'done' else None


@board.route('/board/move', methods=['POST'])
@login_required
def move_task():
    """Drag-and-drop: put a card in a column and renumber that column."""
    data = request.get_json(silent=True) or {}
    task = db.session.get(Task, data.get('id'))
    status = data.get('status')
    if task is None or status not in TASK_STATUSES:
        return jsonify({'ok': False, 'error': 'Unknown card or column.'}), 400
    _set_status(task, status)
    order = [int(i) for i in data.get('order', []) if str(i).isdigit()]
    if order:
        by_id = {t.id: t for t in Task.query.filter(Task.id.in_(order)).all()}
        for pos, tid in enumerate(order, start=1):
            if tid in by_id and by_id[tid].status == status:
                by_id[tid].position = pos
    db.session.commit()
    return jsonify({
        'ok': True,
        'can_log': bool(status == 'done' and task.car_id and not task.event_id),
        'log_url': url_for('board.log_task', task_id=task.id),
    })


@board.route('/board/tasks/<int:task_id>/done', methods=['POST'])
@login_required
def complete_task(task_id):
    task = Task.query.get_or_404(task_id)
    _set_status(task, 'done')
    db.session.commit()
    flash(f'"{task.title}" ticked off.', 'success')
    return redirect(request.form.get('next') or url_for('board.view_board'))


@board.route('/board/tasks/<int:task_id>/log')
@login_required
def log_task(task_id):
    """Turn a finished card into a service event, prefilled from the card."""
    task = Task.query.get_or_404(task_id)
    if not task.car_id:
        flash('Only cards for a car can be logged as a service event.', 'warning')
        return redirect(url_for('board.view_task', task_id=task.id))
    if task.event_id:
        flash('This card has already been logged.', 'info')
        return redirect(url_for('events.view_event', event_id=task.event_id))
    return redirect(url_for('events.add_event', car_id=task.car_id, task=task.id))


@board.route('/board/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    title = task.title
    if task.is_auto:
        # Keep the row so the same reminder isn't raised again this cycle.
        task.status = 'dismissed'
        task.completed_at = datetime.utcnow()
    else:
        db.session.delete(task)
    db.session.commit()
    flash(f'"{title}" rubbed off the board.', 'success')
    return redirect(url_for('board.view_board'))


@board.route('/board/wipe', methods=['POST'])
@login_required
def wipe_done():
    """The eraser: clear the Done column now rather than waiting for it to age out."""
    count = 0
    for task in Task.query.filter_by(status='done').all():
        task.status = 'archived'
        count += 1
    db.session.commit()
    flash(f'Wiped {count} finished card(s) off the board.', 'success')
    return redirect(url_for('board.view_board'))


# ── Parts on a card ─────────────────────────────────────────

@board.route('/board/tasks/<int:task_id>/parts', methods=['POST'])
@login_required
def add_part(task_id):
    task = Task.query.get_or_404(task_id)
    form = TaskPartForm(prefix='part')
    form.stock_item_id.choices = _stock_choices()
    if form.validate_on_submit():
        stock = db.session.get(StockItem, form.stock_item_id.data) if form.stock_item_id.data else None
        part = TaskPart(
            task_id=task.id,
            description=(form.description.data or '').strip() or (stock.name if stock else ''),
            part_number=(form.part_number.data or '').strip() or (stock.part_number if stock else None),
            quantity=form.quantity.data,
            unit_cost=form.unit_cost.data if form.unit_cost.data is not None else (stock.unit_cost if stock else None),
            # A part taken from the shelf is already in hand.
            status='arrived' if stock else 'needed',
            stock_item_id=stock.id if stock else None,
        )
        db.session.add(part)
        db.session.commit()
        if stock and stock.quantity < part.quantity:
            flash(f'Only {stock.quantity:g} {stock.unit} of {stock.name} on the shelf.', 'warning')
        else:
            flash('Part added.', 'success')
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, 'danger')
    return redirect(url_for('board.view_task', task_id=task.id))


@board.route('/board/parts/<int:part_id>/status', methods=['POST'])
@login_required
def set_part_status(part_id):
    part = TaskPart.query.get_or_404(part_id)
    status = request.form.get('status')
    if status in PART_STATUSES:
        part.status = status
        task = part.task
        # All parts in: a card parked in "Waiting on parts" is ready to go.
        if status == 'arrived' and task.status == 'parts' and all(p.status == 'arrived' for p in task.parts):
            _set_status(task, 'todo')
            flash('All parts are in, so the card has moved back to To do.', 'info')
        # Ordering a part for a card in To do parks it until the part arrives.
        elif status == 'ordered' and task.status == 'todo':
            _set_status(task, 'parts')
            flash('Card moved to Waiting on parts.', 'info')
        db.session.commit()
    return redirect(url_for('board.view_task', task_id=part.task_id))


@board.route('/board/parts/<int:part_id>/delete', methods=['POST'])
@login_required
def delete_part(part_id):
    part = TaskPart.query.get_or_404(part_id)
    task_id = part.task_id
    db.session.delete(part)
    db.session.commit()
    flash('Part removed.', 'success')
    return redirect(url_for('board.view_task', task_id=task_id))
