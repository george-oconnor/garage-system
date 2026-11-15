import json
from datetime import date
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required
from garagesystem.models import Car, ServiceEvent, Task, StockItem

main = Blueprint('main', __name__)


@main.route('/')
@main.route('/home')
@login_required
def home():
    cars = Car.query.order_by(Car.date_added.desc()).all()
    recent_events = (
        ServiceEvent.query
        .order_by(ServiceEvent.date.desc())
        .limit(10)
        .all()
    )
    total_spend = sum(c.total_service_spend for c in cars)
    total_events = sum(c.event_count for c in cars)

    from garagesystem.board.utils import sync_auto_tasks, task_urgency
    sync_auto_tasks()
    open_tasks = Task.query.filter(Task.status.in_(('todo', 'parts', 'doing'))).all()
    urgency = {t.id: task_urgency(t) for t in open_tasks}
    # Most pressing first: overdue, then due soon, then whatever's in progress.
    rank = {'overdue': 0, 'soon': 1}
    pressing = sorted(open_tasks, key=lambda t: (rank.get(urgency[t.id], 2), t.status != 'doing',
                                                  t.due_date or date.max, t.position))[:5]
    board_summary = {
        'open': len(open_tasks),
        'overdue': sum(1 for u in urgency.values() if u == 'overdue'),
        'parts': sum(1 for t in open_tasks if t.status == 'parts'),
        'low_stock': sum(1 for s in StockItem.query.all() if s.is_low),
    }

    return render_template(
        'home.html',
        title='Dashboard',
        cars=cars,
        recent_events=recent_events,
        total_spend=total_spend,
        total_events=total_events,
        board_summary=board_summary,
        pressing=pressing,
        urgency=urgency,
    )


@main.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    _instance_dir = os.path.join(os.path.dirname(current_app.root_path), 'instance')
    config_path = os.path.join(current_app.root_path, '..', 'instance', 'config.json')
    config_path = os.path.abspath(config_path)

    if request.method == 'POST':
        # Read existing config so we only overwrite the keys we manage here
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
        else:
            cfg = {}

        provider = request.form.get('vehicle_lookup_provider', 'regcheck')
        cfg['VEHICLE_LOOKUP_PROVIDER'] = provider
        cfg['VEHICLE_LOOKUP_USERNAME'] = request.form.get('vehicle_lookup_username', '').strip()
        cfg['VEHICLEDATAGLOBAL_API_KEY'] = request.form.get('vehicledataglobal_api_key', '').strip()
        cfg['VEHICLEDATAGLOBAL_ENDPOINT'] = request.form.get('vehicledataglobal_endpoint', '').strip() or 'https://ireland.vehicledataglobal.com/api/datapackage/VehicleData'
        cfg['VEHICLEDATAGLOBAL_PACKAGE'] = request.form.get('vehicledataglobal_package', 'VehicleAndMotTests').strip()

        with open(config_path, 'w') as f:
            json.dump(cfg, f, indent=4)

        # Update running app config immediately (takes effect without restart)
        current_app.config['VEHICLE_LOOKUP_PROVIDER'] = cfg['VEHICLE_LOOKUP_PROVIDER']
        current_app.config['VEHICLE_LOOKUP_USERNAME'] = cfg['VEHICLE_LOOKUP_USERNAME']
        current_app.config['VEHICLEDATAGLOBAL_API_KEY'] = cfg['VEHICLEDATAGLOBAL_API_KEY']
        current_app.config['VEHICLEDATAGLOBAL_ENDPOINT'] = cfg['VEHICLEDATAGLOBAL_ENDPOINT']
        current_app.config['VEHICLEDATAGLOBAL_PACKAGE'] = cfg['VEHICLEDATAGLOBAL_PACKAGE']

        flash('Settings saved.', 'success')
        return redirect(url_for('main.settings'))

    return render_template('settings.html', title='Settings')
