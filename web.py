import os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"alive")
    def log_message(self, *a): pass

def keep_alive():
    port = int(os.getenv("PORT", "8080"))
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", port), H).serve_forever(),
        daemon=True
    ).start()
