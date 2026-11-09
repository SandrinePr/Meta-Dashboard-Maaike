from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
import pathlib

OUT = pathlib.Path(
    r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\RRO_Social_strategie_overzicht_2026.xlsx"
)
ROOT = pathlib.Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike")


class H(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "multipart/form-data" in ctype or b"WebKitFormBoundary" in data[:200] or data[:8].startswith(b"------"):
            idx = data.find(b"\r\n\r\n")
            if idx > 0:
                rest = data[idx + 4 :]
                end = rest.rfind(b"\r\n--")
                if end > 0:
                    rest = rest[:end]
                data = rest
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(data)
        body = f"saved {len(data)}".encode()
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    httpd = HTTPServer(("127.0.0.1", 8765), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        str(ROOT / "data/local-https/cert.pem"),
        str(ROOT / "data/local-https/key.pem"),
    )
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("listening https://127.0.0.1:8765", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
