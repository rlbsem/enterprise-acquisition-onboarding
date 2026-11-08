"""Hidden terminal input; inject into the existing read-only acceptance process only."""
import getpass
import os
from pathlib import Path
import runpy
import socket
import sys
import warnings

if not sys.stdin.isatty():
    raise SystemExit('Refusing credential input without a terminal')
warnings.simplefilter('error', getpass.GetPassWarning)
socket.getaddrinfo('api.hubapi.com', 443)
credential = getpass.getpass('HubSpot credential (hidden input): ')
try:
    os.environ['HUBSPOT_SERVICE_KEY'] = credential
    credential = ''
    runpy.run_path(str(Path(__file__).with_name('execute_private.py')), run_name='__main__')
finally:
    credential = ''
    os.environ.pop('HUBSPOT_SERVICE_KEY', None)
