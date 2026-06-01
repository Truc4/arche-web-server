#!/usr/bin/env python3
"""End-to-end tests for arche-web-server: spawn ./server, hit it over HTTP, assert
status / headers / body. Wired to `make test`."""
import http.client
import os
import signal
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = 8137  # unlikely to collide
WWW = os.path.join(ROOT, "www")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        failures.append(name)


def wait_port(port, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def req(method, path):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
    c.request(method, path)
    r = c.getresponse()
    body = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, headers, body


def main():
    server_bin = os.path.join(ROOT, "server")
    if not os.path.exists(server_bin):
        print("server binary missing — run `make` first", file=sys.stderr)
        return 1

    proc = subprocess.Popen([server_bin, str(PORT), WWW],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(PORT):
            print("server did not start", file=sys.stderr)
            return 1

        status, headers, body = req("GET", "/")
        check("GET / -> 200", status == 200, str(status))
        check("GET / is text/html", headers.get("content-type", "").startswith("text/html"))
        check("GET / Content-Length matches body",
              headers.get("content-length") == str(len(body)),
              f'{headers.get("content-length")} vs {len(body)}')
        check("GET / serves index.html", b"It works." in body)

        status, headers, _ = req("GET", "/style.css")
        check("GET /style.css -> 200", status == 200)
        check("/style.css is text/css", headers.get("content-type", "").startswith("text/css"))

        status, headers, _ = req("GET", "/app.js")
        check("/app.js is application/javascript",
              headers.get("content-type") == "application/javascript")

        status, _, _ = req("GET", "/does-not-exist")
        check("missing file -> 404", status == 404, str(status))

        status, _, _ = req("POST", "/")
        check("POST -> 405", status == 405, str(status))

        status, _, _ = req("GET", "/../../etc/passwd")
        check("traversal -> 403", status == 403, str(status))

        status, headers, body = req("HEAD", "/")
        check("HEAD / -> 200", status == 200)
        check("HEAD / has no body", body == b"")
        check("HEAD / still reports Content-Length",
              headers.get("content-length") == "692" or headers.get("content-length") is not None)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print("\nall integration tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
