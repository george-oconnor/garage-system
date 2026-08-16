import requests
from flask import current_app


def _get_graph_token():
    """Acquire an application-only access token via the client credentials grant."""
    tenant_id = current_app.config.get('MSGRAPH_TENANT_ID', '')
    client_id = current_app.config.get('MSGRAPH_CLIENT_ID', '')
    client_secret = current_app.config.get('MSGRAPH_CLIENT_SECRET', '')
    if not (tenant_id and client_id and client_secret):
        return None

    url = f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }
    response = requests.post(url, data=data, timeout=10)
    response.raise_for_status()
    return response.json()['access_token']


def send_password_reset_email(user, reset_url):
    """Send the password reset link to the user via Microsoft Graph's sendMail API.

    Returns True on success, False if Graph is unconfigured or the send fails
    (the caller should log/flash accordingly rather than raise).
    """
    sender = current_app.config.get('MSGRAPH_SENDER', '')
    if not sender:
        current_app.logger.warning('Password reset email not sent: MSGRAPH_SENDER not configured.')
        return False

    try:
        token = _get_graph_token()
        if not token:
            current_app.logger.warning('Password reset email not sent: Microsoft Graph is not configured.')
            return False

        message = {
            'message': {
                'subject': f'{current_app.config.get("APP_NAME", "Garage System")} — Password Reset',
                'body': {
                    'contentType': 'Text',
                    'content': (
                        f'Hi {user.username},\n\n'
                        f'To reset your password, click the link below:\n{reset_url}\n\n'
                        'This link expires in 30 minutes. If you did not request this, you can '
                        'safely ignore this email.\n'
                    ),
                },
                'toRecipients': [{'emailAddress': {'address': user.email}}],
            },
            'saveToSentItems': 'false',
        }
        response = requests.post(
            f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
            json=message,
            headers={'Authorization': f'Bearer {token}'},
            timeout=10,
        )
        if response.status_code >= 300:
            current_app.logger.warning(
                f'Microsoft Graph sendMail failed: HTTP {response.status_code} {response.text[:500]}'
            )
            return False
        return True
    except requests.exceptions.RequestException as exc:
        current_app.logger.warning(f'Microsoft Graph sendMail request failed: {exc}')
        return False
