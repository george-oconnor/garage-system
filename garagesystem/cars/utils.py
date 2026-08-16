import re
import requests
from flask import current_app

IRISH_COUNTY_CODES = {
    'C': 'Cork', 'CE': 'Clare', 'CN': 'Cavan', 'CW': 'Carlow',
    'D': 'Dublin', 'DL': 'Donegal',
    'G': 'Galway',
    'KE': 'Kildare', 'KK': 'Kilkenny', 'KY': 'Kerry',
    'L': 'Limerick', 'LD': 'Longford', 'LH': 'Louth', 'LM': 'Leitrim', 'LS': 'Laois',
    'MH': 'Meath', 'MN': 'Monaghan', 'MO': 'Mayo',
    'OY': 'Offaly',
    'RN': 'Roscommon',
    'SO': 'Sligo',
    'T': 'Tipperary', 'TN': 'North Tipperary', 'TS': 'South Tipperary',
    'W': 'Waterford', 'WD': 'Waterford', 'WH': 'Westmeath', 'WW': 'Wicklow', 'WX': 'Wexford',
}


def parse_irish_plate(registration):
    """
    Parse an Irish registration plate and extract available information.

    Modern format: YY[H]CC-NNNNN
      YY  = 2-digit year (e.g. 23 = 2023)
      H   = half-year indicator: 1 (Jan–Jun) or 2 (Jul–Dec), introduced 2013
      CC  = county code (1–2 letters)
      NNNNN = sequence number

    Examples: 231-D-12345, 14-CE-1234, 07-G-5678
    Returns a dict with parsed fields, or parsed=False if format not recognised.
    """
    reg = registration.upper().strip()
    reg_clean = reg.replace('-', '').replace(' ', '')

    # Pattern: YY + optional half (1|2) + county code (1–2 letters) + sequence digits
    pattern = r'^(\d{2})(1|2)?([A-Z]{1,2})(\d+)$'
    match = re.match(pattern, reg_clean)

    if not match:
        return {'raw': registration, 'parsed': False}

    year_suffix = int(match.group(1))
    half = match.group(2)
    county_code = match.group(3)

    year = (1900 + year_suffix) if year_suffix >= 87 else (2000 + year_suffix)

    half_str = ''
    if half == '1':
        half_str = ' (Jan–Jun)'
    elif half == '2':
        half_str = ' (Jul–Dec)'

    county = IRISH_COUNTY_CODES.get(county_code, f'Unknown ({county_code})')

    return {
        'parsed': True,
        'raw': registration,
        'year': year,
        'year_display': f'{year}{half_str}',
        'county_code': county_code,
        'county': county,
    }


def normalize_fuel_type(raw):
    raw = (raw or '').lower().strip()
    if 'electric' in raw or raw == 'e':
        return 'Electric'
    if 'hybrid' in raw and 'petrol' in raw:
        return 'Hybrid Petrol'
    if 'hybrid' in raw and 'diesel' in raw:
        return 'Hybrid Diesel'
    if 'hybrid' in raw or raw == 'h':
        return 'Hybrid Petrol'
    if 'petrol' in raw or raw == 'p':
        return 'Petrol'
    if 'diesel' in raw or raw == 'd':
        return 'Diesel'
    if raw:
        return 'Other'
    return ''


def normalize_transmission(raw):
    raw = (raw or '').lower().strip()
    if 'semi' in raw or raw == 's':
        return 'Semi-Automatic'
    if 'auto' in raw or raw == 'a':
        return 'Automatic'
    if 'manual' in raw or raw == 'm':
        return 'Manual'
    if raw:
        return 'Other'
    return ''


def normalize_engine_size(raw):
    """Normalise engine size to whole-number cc, e.g. '1800cc'.

    Accepts: '1798', '1798cc', '1798 cc', '1798 CC', '1.8', '1.8L', '1.8l', '2.0L' etc.
    Returns e.g. '1798cc', '1800cc', or '' if not parseable.
    """
    import re as _re
    if not raw:
        return ''
    raw = str(raw).strip()
    # Already numeric cc (optionally suffixed with cc/CC/cm3 etc.)
    m = _re.match(r'^(\d+)\s*(cc|cm3|cm³)?$', raw, _re.IGNORECASE)
    if m:
        return f'{int(m.group(1))}cc'
    # Litre value, e.g. 1.8, 1.8L, 2.0l
    m = _re.match(r'^(\d+\.\d+)\s*(l|litre|liter)?$', raw, _re.IGNORECASE)
    if m:
        return f'{round(float(m.group(1)) * 1000)}cc'
    # Value already has cc somewhere but also has extra text — extract the number
    m = _re.search(r'(\d{3,4})\s*cc', raw, _re.IGNORECASE)
    if m:
        return f'{int(m.group(1))}cc'
    # Fallback: just return as-is so we don't lose info
    return raw


def fetch_car_image(make, model, year=None):
    """Fetch a thumbnail URL from Wikimedia Commons for the given make/model/year.

    Uses the Commons file-search API with a year-specific query first, falling
    back to make+model only. Returns the first bitmap result at 800px width, or
    None if nothing found.
    """
    import requests as _req
    headers = {'User-Agent': 'GarageSystem/1.0 (personal car maintenance app)'}

    make_t = make.title()
    model_t = model.title()
    model_l = model.lower()

    # Build candidate queries: most specific first
    queries = []
    if year:
        queries.append(f'{make_t} {model_l} {year}')
        queries.append(f'{make_t} {model_t} {year}')
    queries.append(f'{make_t} {model_l}')
    queries.append(f'{make_t} {model_t}')

    def _search(query):
        try:
            resp = _req.get(
                'https://commons.wikimedia.org/w/api.php',
                params={
                    'action': 'query',
                    'generator': 'search',
                    'gsrsearch': f'filetype:bitmap {query}',
                    'gsrnamespace': 6,
                    'gsrlimit': 5,
                    'prop': 'imageinfo',
                    'iiprop': 'url|mime',
                    'iiurlwidth': 800,
                    'format': 'json',
                },
                headers=headers,
                timeout=8,
            )
            pages = resp.json().get('query', {}).get('pages', {})
            for page in pages.values():
                ii = page.get('imageinfo', [{}])[0]
                mime = ii.get('mime', '')
                if mime.startswith('image/') and 'svg' not in mime:
                    url = ii.get('thumburl') or ii.get('url')
                    if url:
                        return url
        except Exception:
            pass
        return None

    seen = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        url = _search(q)
        if url:
            return url
    return None


def lookup_vehicle_api(registration):
    """
    Dispatch vehicle lookup to the configured provider.
    Returns (data_dict, error_reason, raw_response_text).
    """
    provider = current_app.config.get('VEHICLE_LOOKUP_PROVIDER', 'regcheck')
    if provider == 'vehicledataglobal':
        return _lookup_vehicledataglobal(registration)
    return _lookup_regcheck(registration)


def _lookup_regcheck(registration):
    """
    Look up via regcheck.org.uk CheckIreland.
    Requires VEHICLE_LOOKUP_USERNAME in config.
    Returns (data_dict, error_str) or (None, None) if unconfigured.
    """
    import xml.etree.ElementTree as ET
    import json as _json

    username = current_app.config.get('VEHICLE_LOOKUP_USERNAME', '')
    if not username:
        return None, None, None

    # Strip spaces/dashes so the plate is clean for the API
    reg_clean = registration.upper().replace('-', '').replace(' ', '')

    url = 'https://www.regcheck.org.uk/api/reg.asmx/CheckIreland'
    try:
        response = requests.get(
            url,
            params={'RegistrationNumber': reg_clean, 'username': username},
            timeout=15,
        )
        current_app.logger.debug(
            f'regcheck response for {reg_clean}: HTTP {response.status_code}\n{response.text[:500]}'
        )
        if response.status_code != 200:
            reason = f'API returned HTTP {response.status_code}'
            current_app.logger.warning(f'regcheck: {reason} for {reg_clean}')
            return None, reason, response.text

        # Response is XML; the vehicle data lives inside <vehicleJson>
        root = ET.fromstring(response.text)
        # Namespace in response is http://regcheck.org.uk (no www, no https, no trailing slash)
        ns_uri = root.tag.split('}')[0].lstrip('{') if root.tag.startswith('{') else ''
        ns_prefix = f'{{{ns_uri}}}' if ns_uri else ''
        json_node = root.find(f'{ns_prefix}vehicleJson')
        if json_node is None or not json_node.text:
            current_app.logger.warning(
                f'regcheck: no vehicleJson for {reg_clean}. Raw response:\n{response.text[:800]}'
            )
            return None, 'Vehicle not found in regcheck database', response.text

        data = _json.loads(json_node.text)
        current_app.logger.debug(f'regcheck parsed JSON for {reg_clean}: {data}')

        # Only bail on an explicit Error string (not StatusCode, which appears on success too)
        if data.get('Error') and not (data.get('MakeDescription') or data.get('Make')):
            error_msg = str(data['Error'])
            current_app.logger.warning(f'regcheck: API error for {reg_clean}: {error_msg}')
            return None, error_msg, response.text

        def _text(field):
            """Extract CurrentTextValue from a nested dict field, or return the field itself."""
            val = data.get(field)
            if isinstance(val, dict):
                return val.get('CurrentTextValue') or val.get('CurrentTypeInfo') or ''
            return val or ''

        return {
            'make':         _text('MakeDescription') or _text('Make'),
            'model':        _text('ModelDescription') or _text('CarModel') or _text('Model'),
            'variant':      data.get('Description', ''),
            'colour':       _text('ColourCurrent'),
            'fuel_type':    _text('FuelType'),
            'engine_size':  normalize_engine_size(_text('EngineSize')),
            'transmission': _text('Transmission'),
            'year':         data.get('RegistrationYear') or data.get('YearOfManufacture'),
            'description':  data.get('Description', ''),
        }, None, response.text

    except requests.exceptions.Timeout:
        current_app.logger.warning(f'regcheck timed out for {reg_clean}')
        return None, 'regcheck timed out — the service may be slow. Try again in a moment.', None
    except requests.exceptions.ConnectionError:
        current_app.logger.warning(f'regcheck connection error for {reg_clean}')
        return None, 'Could not connect to regcheck — check your internet connection.', None
    except Exception as exc:
        current_app.logger.warning(f'regcheck lookup failed for {reg_clean}: {exc}')
        return None, 'regcheck lookup failed — please fill in the details manually.', None


def _lookup_vehicledataglobal(registration):
    """
    Look up via vehicledataglobal.com ROI endpoint.
    Requires VEHICLEDATAGLOBAL_API_KEY in config.
    Returns (data_dict, error_str) or (None, None) if unconfigured.
    """
    import json as _json

    api_key = current_app.config.get('VEHICLEDATAGLOBAL_API_KEY', '')
    if not api_key:
        return None, None, None

    endpoint = current_app.config.get(
        'VEHICLEDATAGLOBAL_ENDPOINT',
        'https://ireland.vehicledataglobal.com/api/datapackage/VehicleData',
    )
    package = current_app.config.get('VEHICLEDATAGLOBAL_PACKAGE', 'VehicleAndMotTests')
    reg_clean = registration.upper().replace('-', '').replace(' ', '')

    try:
        response = requests.get(
            endpoint,
            params={'packageName': package, 'vrm': reg_clean},
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=15,
        )
        current_app.logger.debug(
            f'VDG response for {reg_clean}: HTTP {response.status_code}\n{response.text[:800]}'
        )
        if response.status_code != 200:
            return None, f'API returned HTTP {response.status_code}', response.text

        data = _json.loads(response.text)

        resp_info = data.get('ResponseInformation') or data.get('responseInformation') or {}
        is_success = resp_info.get('IsSuccessStatusCode') or resp_info.get('isSuccessStatusCode')
        if not is_success:
            msg = (resp_info.get('StatusMessage') or resp_info.get('statusMessage') or 'Unknown error')
            current_app.logger.warning(f'VDG error for {reg_clean}: {msg}')
            # Translate known VDG status codes into actionable messages
            msg_upper = msg.upper()
            if 'SANDBOXVALIDATIONFAILURE' in msg_upper:
                msg = ('VehicleDataGlobal: plate format not recognised — '
                       'try switching to regcheck in Settings for this plate.')
            elif 'NORECORDFOUND' in msg_upper or 'NO RECORD' in msg_upper:
                msg = 'VehicleDataGlobal: no record found for this plate.'
            elif 'UNAUTHORISED' in msg_upper or 'UNAUTHORIZED' in msg_upper:
                msg = 'VehicleDataGlobal: invalid API key — check Settings.'
            return None, msg, response.text

        # PHP class: UkvdResponse.$results -> LookupResults.$roiVehicleDetails
        # Try both camelCase and PascalCase variants
        lookup = (
            data.get('results')
            or data.get('Results')
            or data.get('LookupResults')
            or data.get('lookupResults')
            or {}
        )
        details = (
            lookup.get('roiVehicleDetails')
            or lookup.get('RoiVehicleDetails')
            or data.get('roiVehicleDetails')
            or data.get('RoiVehicleDetails')
        )

        if not details:
            current_app.logger.warning(
                f'VDG: no RoiVehicleDetails for {reg_clean}. Top-level keys: {list(data.keys())}'
                + (f', results keys: {list(lookup.keys())}' if lookup else '')
            )
            return None, 'Vehicle not found in VehicleDataGlobal database', response.text

        current_app.logger.debug(f'VDG details for {reg_clean}: {details}')

        # statusMessage of 'NOT ENABLED' means the package doesn't include this data item
        status_msg = (details.get('StatusMessage') or details.get('statusMessage') or '').upper()
        if 'NOT ENABLED' in status_msg or details.get('StatusCode', 0) in (1, '1'):
            current_app.logger.warning(f'VDG: data item not enabled for {reg_clean}: {status_msg}')
            return None, f'VehicleDataGlobal: {details.get("StatusMessage", "feature not enabled for this package")}', response.text

        def _vdg(field):
            """Return field value, treating 'Not Enabled' / 'NOT ENABLED' as empty."""
            val = (details.get(field) or '').strip()
            return '' if val.upper() in ('NOT ENABLED', 'NOT_ENABLED', 'NOTENABLED') else val

        year = _vdg('BuildYear')
        if not year:
            dofr = _vdg('DateOfFirstRegistration')
            year = dofr[:4] if dofr else ''

        base_model = _vdg('Model')
        description = _vdg('Description')

        return {
            'make':         _vdg('Make'),
            'model':        base_model,
            'variant':      description,   # full trim line e.g. "1.8T VECTOR CONVERTIBLE 2DR"
            'colour':       _vdg('Colour'),
            'fuel_type':    _vdg('FuelType'),
            'engine_size':  normalize_engine_size(_vdg('EngineCapacity')),
            'transmission': _vdg('Transmission'),
            'year':         year,
            'description':  description,
            'vin':          _vdg('Vin'),
        }, None, response.text

    except requests.exceptions.ConnectionError:
        current_app.logger.warning(f'VDG lookup: could not connect to {endpoint} for {reg_clean}')
        return None, 'Could not connect to VehicleDataGlobal — check the endpoint URL in Settings.', None
    except requests.exceptions.Timeout:
        current_app.logger.warning(f'VDG timed out for {reg_clean}')
        return None, 'VehicleDataGlobal timed out — try again in a moment.', None
    except Exception as exc:
        current_app.logger.warning(f'VDG lookup failed for {reg_clean}: {exc}')
        return None, 'VehicleDataGlobal lookup failed — please fill in the details manually.', None
