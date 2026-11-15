from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from garagesystem.csrf import check_post_csrf

from garagesystem import db
from garagesystem.models import StockItem, Task, TaskPart, EventLineItem
from garagesystem.shelf.forms import StockItemForm, STOCK_CATEGORIES

shelf = Blueprint('shelf', __name__)


shelf.before_request(check_post_csrf)



def _apply_form(item, form):
    old_qty = item.quantity
    item.name = form.name.data.strip()
    item.category = form.category.data
    item.part_number = (form.part_number.data or '').strip() or None
    item.quantity = form.quantity.data or 0
    item.unit = form.unit.data
    item.unit_cost = form.unit_cost.data
    item.min_quantity = form.min_quantity.data
    item.location = (form.location.data or '').strip() or None
    item.fits = (form.fits.data or '').strip() or None
    item.notes = (form.notes.data or '').strip() or None
    if old_qty is None or item.quantity > old_qty:
        item.last_restocked = datetime.utcnow()


@shelf.route('/shelf')
@login_required
def view_shelf():
    items = StockItem.query.order_by(StockItem.name).all()
    order = [c for c, _ in STOCK_CATEGORIES]
    grouped = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)
    groups = sorted(grouped.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order))
    stock_value = round(sum((i.unit_cost or 0) * i.quantity for i in items), 2)
    form = StockItemForm()
    return render_template('shelf/shelf.html', title='Shelf', groups=groups, form=form,
                           item_count=len(items), low_count=sum(1 for i in items if i.is_low),
                           stock_value=stock_value)


@shelf.route('/shelf/new', methods=['POST'])
@login_required
def add_item():
    form = StockItemForm()
    if form.validate_on_submit():
        item = StockItem(quantity=None)
        _apply_form(item, form)
        db.session.add(item)
        db.session.commit()
        flash(f'{item.name} added to the shelf.', 'success')
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, 'danger')
    return redirect(url_for('shelf.view_shelf'))


@shelf.route('/shelf/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = StockItem.query.get_or_404(item_id)
    form = StockItemForm(obj=item)
    if form.validate_on_submit():
        _apply_form(item, form)
        db.session.commit()
        flash(f'{item.name} updated.', 'success')
        return redirect(url_for('shelf.view_shelf'))
    used = (EventLineItem.query.filter_by(stock_item_id=item.id)
            .order_by(EventLineItem.date_added.desc()).limit(20).all())
    return render_template('shelf/edit_item.html', title=f'Edit {item.name}', form=form, item=item, used=used)


@shelf.route('/shelf/<int:item_id>/adjust', methods=['POST'])
@login_required
def adjust_item(item_id):
    """Quick +/- buttons on the shelf list."""
    item = StockItem.query.get_or_404(item_id)
    try:
        delta = float(request.form.get('delta', 0))
    except ValueError:
        delta = 0
    if delta:
        item.quantity = max(0.0, round(item.quantity + delta, 3))
        if delta > 0:
            item.last_restocked = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('shelf.view_shelf') + f'#stock-{item.id}')


@shelf.route('/shelf/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    item = StockItem.query.get_or_404(item_id)
    name = item.name
    # SQLite doesn't enforce ON DELETE SET NULL unless foreign keys are on,
    # so unlink anything pointing here explicitly.
    for model in (EventLineItem, TaskPart, Task):
        model.query.filter_by(stock_item_id=item.id).update({'stock_item_id': None})
    db.session.delete(item)
    db.session.commit()
    flash(f'{name} removed from the shelf.', 'success')
    return redirect(url_for('shelf.view_shelf'))
