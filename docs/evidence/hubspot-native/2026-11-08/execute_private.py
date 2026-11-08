"""One authorized CLI execution plus independent GET-only verification. No credential output."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import certifi

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'results-04'
EXPECTED_REVISION = '0e6a5b6ae0ef0cf05b75f636e9ab5676499b1cf4'
COMPANY, CONTACT = '229684469730', '288567817180'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    secret = os.environ.get('HUBSPOT_SERVICE_KEY', '')
    if not secret or any(c in secret for c in '\r\n'):
        print(json.dumps({'outcome': 'blocked', 'reason': 'credential_missing_or_invalid_shape'}))
        return 2
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if revision != EXPECTED_REVISION:
        print(json.dumps({'outcome': 'blocked', 'reason': 'source_revision_changed'}))
        return 2
    OUT.mkdir(exist_ok=False)

    def save(name, data):
        text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
        if secret in text or 'pat-na3-' in text:
            raise RuntimeError('credential_output_blocked')
        (OUT / name).write_text(text, encoding='utf-8', newline='\n')

    sources = ['src/onboarding/hubspot_native.py', 'requirements.lock', 'pyproject.toml',
               'tests/test_hubspot_native.py']
    save('source.json', {'source_revision': revision,
         'source_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sources},
         'started_at_utc': now(), 'python': sys.version.split()[0],
         'key_storage': 'process environment only; not included in artifacts',
         'portal_identity_boundary': 'Expected portal 343801908 was verified in the Service Key UI; these object GETs do not independently authenticate portal ID.'})
    started = now()
    cli = subprocess.run([sys.executable, '-m', 'onboarding.hubspot_native', '--read-only'],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=35)
    try:
        result = json.loads(cli.stdout)
    except ValueError:
        result = {'outcome': 'blocked', 'reason': 'cli_output_not_json'}
    save('cli.json', {'command': 'python -m onboarding.hubspot_native --read-only',
                     'started_at_utc': started, 'completed_at_utc': now(),
                     'returncode': cli.returncode, 'result': result,
                     'stderr_present': bool(cli.stderr), 'stderr_content_retained': False})
    if result.get('reason') in ('service_key_access_denied', 'provider_rate_limited_no_replay'):
        print(json.dumps({'outcome': 'blocked', 'reason': result['reason'], 'native_returncode': cli.returncode}))
        return 2

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
              urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    observed = []
    for kind, identifier, properties, target in (
            ('companies', COMPANY, 'name', 'contacts'),
            ('contacts', CONTACT, 'firstname,lastname,email', 'companies')):
        path = f'/crm/objects/2026-09/{kind}/{identifier}'
        request = urllib.request.Request('https://api.hubapi.com' + path + '?' +
                  urllib.parse.urlencode({'properties': properties, 'associations': target}),
                  headers={'Authorization': 'Bearer ' + secret, 'Accept': 'application/json'}, method='GET')
        record = {'method': 'GET', 'path': path, 'properties_requested': properties,
                  'associations_requested': target, 'observed_at_utc': now()}
        try:
            with opener.open(request, timeout=7) as response:
                raw = response.read(65537)
                record['status_code'] = response.status
                record['correlation_id'] = response.headers.get('x-hubspot-correlation-id')
                record['response_date'] = response.headers.get('date')
            if len(raw) > 65536:
                raise ValueError('response_size_exceeded')
            body = json.loads(raw)
            record['response_body_sha256'] = hashlib.sha256(raw).hexdigest()
            record['source'] = {k: body.get(k) for k in ('id', 'archived', 'createdAt', 'updatedAt')}
            record['source']['properties'] = {n: body.get('properties', {}).get(n) for n in properties.split(',')}
            link = body.get('associations', {}).get(target, {})
            record['source']['association_results'] = [
                {k: row.get(k) for k in ('id', 'type')} for row in link.get('results', [])]
            record['source']['association_paging_present'] = bool(link.get('paging', {}).get('next'))
        except urllib.error.HTTPError as exc:
            record['status_code'] = exc.code
            record['outcome'] = 'http_error_no_body_retained'
        except Exception as exc:
            record['outcome'] = 'independent_read_failed'
            record['error_type'] = type(exc).__name__
            reason = getattr(exc, 'reason', None)
            record['transport_reason_type'] = type(reason).__name__
            record['transport_errno'] = getattr(reason, 'errno', None)
            record['transport_winerror'] = getattr(reason, 'winerror', None)
            record['certificate_verify_code'] = getattr(reason, 'verify_code', None)
        observed.append(record)
        save('independent-responses.json', observed)
        if record.get('status_code') in (401, 403, 429):
            break
    checks = {}
    if len(observed) == 2 and all(r.get('status_code') == 200 and 'source' in r for r in observed):
        company, contact = [r['source'] for r in observed]
        checks = {
            'company_id': company['id'] == COMPANY,
            'contact_id': contact['id'] == CONTACT,
            'neither_archived': company['archived'] is False and contact['archived'] is False,
            'company_properties': company['properties'] == {'name': 'Cedar Services — Synthetic Acceptance'},
            'contact_properties': contact['properties'] == {'firstname': 'Cedar', 'lastname': 'Test Contact', 'email': 'cedar.test.contact@example.com'},
            'company_to_contact': {r['id'] for r in company['association_results']} == {CONTACT},
            'contact_to_company': {r['id'] for r in contact['association_results']} == {COMPANY},
            'no_repeated_typed_links': all(len(s['association_results']) == len({(r['id'],r['type']) for r in s['association_results']}) for s in (company, contact)),
            'no_paged_association': not company['association_paging_present'] and not contact['association_paging_present'],
        }
    passed = cli.returncode == 0 and result.get('outcome') == 'verified' and bool(checks) and all(checks.values())
    final = {'outcome': 'verified' if passed else 'blocked', 'completed_at_utc': now(),
             'source_revision': revision, 'cli_verified': cli.returncode == 0 and result.get('outcome') == 'verified',
             'independent_checks': checks, 'native_cli_requests_expected': 2,
             'independent_requests_observed': len(observed), 'crm_writes': 0,
             'native_provider': 'actual api.hubapi.com HTTPS, no connector or mock transport',
             'verified_portal_id_by_api': False}
    save('acceptance.json', final)
    print(json.dumps(final))
    return 0 if passed else 2


if __name__ == '__main__':
    try:
        code = main()
    except Exception as error:
        print(json.dumps({'outcome': 'blocked', 'error_type': type(error).__name__, 'detail_retained': False}))
        code = 2
    finally:
        os.environ.pop('HUBSPOT_SERVICE_KEY', None)
    sys.exit(code)
