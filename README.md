# arche-web-server

A static-file HTTP/1.1 server written in [Arche](../arche) — a data-oriented language compiled
through LLVM. It doubles as a **reference for idiomatic Arche**: the device/driver library model,
totality (proven bounds + failure policies, so the server can't crash on a bad request), ownership
without a GC, and `match`-based dispatch — all in ~140 lines of pure Arche, no C and no `--link`
(networking is the built-in `socket` opaque + `#import net`).

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

## What it showcases

- **Devices & drivers** — `server.arche` is a *device* (routing + handlers); `main.arche` is the
  *driver* that owns all storage (it sizes the router's `TrieNode[256]` pool) and runs the accept loop.
- **Totality** — every array write the app makes (path assembly in `build_path`) is *proven* in range
  by a capacity-bounded loop, so it can never overflow or abort; no failure policy is even needed.
  (A policy like `a[i] !clamp` / `!zero` is the fallback for an index the prover *can't* bound; this
  server doesn't have one, so it stays total by construction. See the language reference.)
- **Ownership without a GC** — buffers move into helpers (`move path`), opaque `socket`/`fd` handles
  auto-drop (close) on every return path.
- **`match` dispatch** — the router resolves a path to an enum route id; a `match` is the dispatch
  table (Arche has no runtime function pointers), exhaustive with no `_` arm.

## Scope / limitations

One blocking connection at a time; one `recv` per request (request line + headers must fit ~8 KB,
fine on localhost); files served in a single read (≤ 256 KB). These are demo simplifications, not
language limits.

## Layout

```
src/main.arche     the driver: owns storage (router's pool), parses argv, runs the accept loop
src/server.arche   the `server` device: route registration, the per-connection handler, file serving
www/               static content (index.html, about.html, style.css, app.js)
tests/             integration tests (spawns ./server, exercises it over HTTP)
```
