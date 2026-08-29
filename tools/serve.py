#!/usr/bin/env python3
"""Local server that mirrors the Vercel config: cleanUrls, trailingSlash:false,
and the 404 page. Without this, extensionless links work in production but
404 locally, which makes local verification misleading."""
import http.server, os, socketserver, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def translate_path(self, path):
        p = super().translate_path(path)
        if os.path.isdir(p):
            idx = os.path.join(p, 'index.html')
            if os.path.exists(idx):
                return idx
        # cleanUrls: /menu -> menu.html
        if not os.path.exists(p) and not os.path.splitext(p)[1]:
            html = p + '.html'
            if os.path.exists(html):
                return html
        return p

    def send_error(self, code, message=None, explain=None):
        if code == 404:
            page = os.path.join(ROOT, '404.html')
            if os.path.exists(page):
                body = open(page, 'rb').read()
                self.send_response(404)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        super().send_error(code, message, explain)

    def log_message(self, *a):
        pass

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('', PORT), Handler) as httpd:
    print(f"serving {ROOT} on http://localhost:{PORT}  (cleanUrls enabled)")
    httpd.serve_forever()
