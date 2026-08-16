import os
import json

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_instance_dir = os.path.join(_pkg_dir, '..', 'instance')
_config_path = os.path.join(_instance_dir, 'config.json')

_config = {}
if os.path.exists(_config_path):
    with open(_config_path) as _f:
        _config = json.load(_f)


class Config:
    SECRET_KEY = _config.get('SECRET_KEY') or os.environ.get('SECRET_KEY') or 'dev-secret-key-please-change'

    _db_path = os.path.abspath(os.path.join(_instance_dir, 'garage.db'))
    SQLALCHEMY_DATABASE_URI = (
        _config.get('SQLALCHEMY_DATABASE_URI')
        or os.environ.get('DATABASE_URL')
        or f'sqlite:///{_db_path}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SYSTEM = _config.get('SYSTEM') or os.environ.get('SYSTEM') or 'DEVELOPMENT'

    SENTRY_DSN = _config.get('SENTRY_DSN') or os.environ.get('SENTRY_DSN') or ''
    SENTRY_ENVIRONMENT = _config.get('SENTRY_ENVIRONMENT') or SYSTEM

    SESSION_TYPE = 'filesystem'
    SESSION_FILE_DIR = os.path.join(_pkg_dir, '..', 'flask_session')

    REDIS_URL = _config.get('REDIS_URL') or os.environ.get('REDIS_URL') or 'redis://localhost:6379'

    # Optional: regcheck.org.uk vehicle lookup (Irish plates).
    # Sign up at regcheck.org.uk — your registered username is the credential.
    # The app works fine without this; the free plate parser still runs.
    VEHICLE_LOOKUP_USERNAME = _config.get('VEHICLE_LOOKUP_USERNAME') or ''

    # Optional: VehicleDataGlobal API (vehicledataglobal.com) — alternative provider.
    # Requires an API key and the ROI endpoint/package name.
    VEHICLEDATAGLOBAL_API_KEY = _config.get('VEHICLEDATAGLOBAL_API_KEY') or ''
    VEHICLEDATAGLOBAL_ENDPOINT = (
        _config.get('VEHICLEDATAGLOBAL_ENDPOINT')
        or 'https://uk.api.vehicledataglobal.com/r2/lookup'
    )
    VEHICLEDATAGLOBAL_PACKAGE = _config.get('VEHICLEDATAGLOBAL_PACKAGE') or 'ROIVehicleDetails'

    # Which provider to use: 'regcheck' or 'vehicledataglobal'
    VEHICLE_LOOKUP_PROVIDER = _config.get('VEHICLE_LOOKUP_PROVIDER') or 'regcheck'

    # Microsoft Graph API — used to send password reset emails via an Azure AD
    # app registration (application permission: Mail.Send, admin-consented).
    MSGRAPH_TENANT_ID = _config.get('MSGRAPH_TENANT_ID') or os.environ.get('MSGRAPH_TENANT_ID') or ''
    MSGRAPH_CLIENT_ID = _config.get('MSGRAPH_CLIENT_ID') or os.environ.get('MSGRAPH_CLIENT_ID') or ''
    MSGRAPH_CLIENT_SECRET = _config.get('MSGRAPH_CLIENT_SECRET') or os.environ.get('MSGRAPH_CLIENT_SECRET') or ''
    # Mailbox the reset email is sent from (must be a real mailbox the app registration can send as).
    MSGRAPH_SENDER = _config.get('MSGRAPH_SENDER') or os.environ.get('MSGRAPH_SENDER') or ''

    APP_NAME = 'Garage System'
    CURRENCY_SYMBOL = '€'
    MILEAGE_UNIT = 'km'
