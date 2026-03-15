from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import threading
import sys

def get_tanks_for_player(account_id):
    """
    Given a WoT account_id (int), return a list of WoT internal tank name strings.
    """
    # Example stub — replace with real logic if needed in the future
    print(f'[server] Request for account_id={account_id}')
 
    # Hardcoded test response as requested:
    return [
        'uk:GB98_T95_FV4201_Chieftain',
        'ussr:R97_Object_140',
        'germany:G56_E-100',
    ]

class TankRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
 
        if parsed.path == '/tanks':
            account_id = params.get('account_id', [None])[0]
            if not account_id:
                self._respond(400, {'error': 'account_id is required'})
                return
            try:
                account_id = int(account_id)
                # Use callback from the server instance if provided
                if hasattr(self.server, 'get_tanks_cb') and self.server.get_tanks_cb:
                    tanks = self.server.get_tanks_cb(account_id)
                else:
                    tanks = []
                self._respond(200, {'tanks': tanks})
            except Exception as e:
                self._respond(500, {'error': str(e)})
        else:
            self._respond(404, {'error': 'not found'})
 
    def _respond(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*') # Add CORS just in case
        self.end_headers()
        self.wfile.write(body)
 
    def log_message(self, format, *args):
        # Redirect log messages to stdout so they can be captured by the UI log redirector
        print('[server] ' + format % args)

class TankServer:
    def __init__(self, host='localhost', port=8082, get_tanks_cb=None):
        self.host = host
        self.port = port
        self.get_tanks_cb = get_tanks_cb
        self.server = None
        self.thread = None

    def start(self):
        try:
            self.server = HTTPServer((self.host, self.port), TankRequestHandler)
            self.server.get_tanks_cb = self.get_tanks_cb
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            print(f'[server] Running on http://{self.host}:{self.port}')
        except Exception as e:
            print(f'[server] Failed to start: {e}', file=sys.stderr)

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            print('[server] Stopped.')
