# arche-web-server

A static-file HTTP/1.1 server written in [Arche](../arche) — a data-oriented language compiled
through LLVM. **The point isn't the server; it's stress-testing the language.** Every limitation
hit while building it is logged in [`FINDINGS.md`](./FINDINGS.md) and, where possible, fixed in the
compiler itself.

## Run it

```sh
make
./server 8080 www
# then open http://localhost:8080/
```

`server <port> <www-root>` serves files under `<www-root>`.

## What it does

- **GET / HEAD** for static files; **405** for anything else.
- **MIME by extension** (`.html .htm .css .js .json .png .jpg .svg .txt`, else `octet-stream`).
- **Content-Length** and `Connection: close` on every response.
- **404** for missing files, **403** for `..` path traversal, **`/` → `/index.html`**, query
  strings stripped.

## Test

```sh
make test          # spawns ./server and exercises it over HTTP (tests/integration/test_http.py)
```

## Scope / limitations

One blocking connection at a time; one `recv` per request (request line + headers must fit ~8 KB,
fine on localhost); files served in a single read (≤ 256 KB). These are demo simplifications, not
language limits — see `FINDINGS.md` for the real language findings (and the fixes that landed in the
compiler, e.g. the `_` shadow placeholder and copy-elision).

## Layout

```
src/main.arche   the whole server (single file; socket I/O inlined in main — see FINDINGS)
www/             static content (index.html, about.html, style.css, app.js)
tests/           integration tests
FINDINGS.md      the actual deliverable: language limits + fixes
```
