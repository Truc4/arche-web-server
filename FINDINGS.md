# arche findings — from building arche-web-server

This project's #1 goal is to **stress-test arche and find its limits** by building an HTTP
server in it. The web server is the vehicle; making the language better is the deliverable.
Each limit below is written so it is independently actionable as a language fix, mirroring
`/home/curt/Code/arche-net-demo/FINDINGS.md`. Verified against the compiler at
`/home/curt/Code/arche`.

Workflow per finding: record here → (decide fix/defer/spec) → design spec in
`arche/docs/superpowers/specs/` → unit test in `arche/tests/unit/language/` → implement →
`build/arche test` → flip the entry to `✅ FIXED` with compiler location + test + spec.

## Milestones

- **A — raw TCP echo** ✅ done. Confirmed the socket surface (`#import net;`, `socket` opaque,
  `net_listen(p)(s:)` out-param calls, `net_close(move s)`).
- **B — request line parse + status** ✅ folded into C.
- **C — static-file server** ✅ done (`src/main.arche` + `www/`). GET/HEAD, MIME by extension,
  Content-Length, 404/403/405, `/`→`/index.html`, query-string strip. 13 end-to-end tests pass
  (`tests/integration/test_http.py`, `make test`). Verified with `curl`.
- **D — routing / E — concurrency**: not built — the demo is a single-blocking-connection static
  server by design. Concurrency (non-blocking + `poll()` in `runtime/net.c`) is the next real
  language/runtime finding, left as future work.

## Model clarified (not bugs)

1. **Passing an array to an extern without copy/move → in-out, which is a *shadow*. ✅ UNDERSTOOD.**
   An array in-param can never be a plain read-only borrow into an extern (`semantic.c:2703` —
   correct, by design): it must be `own` (caller `move`/`copy`) or **in-out** (same name in the
   in-list and out-list). In-out is not a mutation claim — the out-param *shadows* the in-param;
   it's purely the mechanism that lets an array pass by reference and line up the C args. So
   read-only externs (send, fd-write, hash) use in-out, and that is correct, not a lie.
   - **Change kept:** `stdlib/net/net.arche` `net_send` → `(s: socket, buf: char[], n: int)(buf:
     char[], r: int)`, symmetric with `net_recv`. `socket_loopback.arche` still green.

## Limitations found

3. **An in-out in-arg at a call site appeared to pass an array into an extern without move/copy —
   it violated the language's own invariant. ✅ FIXED (new `_` placeholder + copy-elision).**
   Resolution shipped two compiler features:
   - **`_` shadow placeholder.** `_` is now a legal call argument *only* for an in-out in-param;
     it means "no value passed here — use the out-binding's place," zero-copy. A bare array no
     longer has to sit in the in-slot. Misuse (`_` on a non-in-out param) errors with E0115.
     Impl: `semantic/semantic.c` (skip name-resolution for `_` in a call arg, validate the
     positional in-param is in-out via `proc_param_is_inout`, never add `_` as a symbol) +
     `codegen/codegen.c` (pass the matching out-binding buffer pointer). No parser change — `_`
     already lexes as a name. Diagnostic E0115 added in `sem_diagnostics.{h,c}`.
   - **Copy-elision.** `copy x` into an in-out param whose out-binding is the same `x` now emits
     no `llvm.memcpy` — the caller already consents to `x` being written (it's the out place), so
     it's passed by reference. A `copy` into a plain `own` param (no matching out-binding) still
     copies. Impl: `codegen/codegen.c` call-arg path skips the `UNARY_COPY` node in that case.
   - **Tests:** `tests/unit/language/calls/inout_underscore.arche` (runs, prints `X`),
     `tests/unit/language/calls/copy_inout_elided.arche` (asserts no `llvm.memcpy` in IR). Full
     suite green (lit 324/324). Server now uses `net_send(conn, _, n)(buf, _sent:)` — 0 memcpys.

   <details><summary>original symptom</summary>
   The language's logic (`semantic.c:2703`) is: you can never pass a bare array into an in-param —
   it must be `move`/`copy`'d. But for an in-out param the call site currently *does* accept a bare
   array name in the in-slot: `net_send(conn, buf, n)(buf, _sent:)` — the `buf` in the in-list
   looks exactly like a bare-array in-arg with no `move`/`copy`. It's tolerated only because the
   out-param shadows it, so that in-value is never actually used. So the call reads as a violation
   of the very rule the language enforces elsewhere. The correct form is a `_` placeholder in the
   shadowed in-slot — `net_send(conn, _, n)(buf, _sent:)` — signalling "nothing real is passed
   here; the out-binding shadows it." But `_` as a call argument fails today with
   `Semantic error: Undefined symbol '_'` (it's only a match wildcard, `parser.c:1622`, and the
   unused-binding prefix).
   - **Repro:** `net_send(conn, _, n)(buf, _sent:)` in `src/main.arche`. Worked around by the
     (inconsistent-looking) bare-name form `net_send(conn, buf, n)(buf, _sent:)`.
   - **Suspected fix (two halves):** (a) accept `_` as a call argument that, for an in-param
     shadowed by an in-out out-binding, denotes the shadow (no value passed) — parser allows `_`
     as an argument hole, `lower`/`semantic` ties it to the matching out-binding, codegen passes
     the shadowed place. (b) Decide whether a *bare array name* in an in-out in-slot should then be
     rejected (forcing `_`, keeping the invariant airtight) or stay allowed as sugar.
   </details>

## Limitations found (deferred)

2. **A local shadowing a core proc name gives a baffling type error, not a shadow/clash — DEFERRED.**
   Naming a local `open := 1` (intending a loop flag) made `open = 0` fail with
   `assignment: expected 'proc(2)(1)', got 'int'` — the bare name `open` resolved to core's
   `open` syscall proc instead of the new local, with no hint that a core name was shadowed.
   - **Repro:** rename the echo loop's `live` flag back to `open` in `src/main.arche`.
   - **Not a misplacement.** First guess was "move `open` into `io`". But core's
     `open`/`read`/`write`/`close`/`lseek` are an *intentional* raw-fd primitive layer (core
     header lines 9-10) with their own tests (`tests/unit/language/syscall/raw_io_wrappers.arche`,
     `builtins/test_open_close.arche`, `builtins/test_open_read.arche`). `io` builds the
     `file`-typed `io.open`/`io.close` on top. So both exist by design; removing core's `open`
     would break documented primitives. The clash is purely a scoping/diagnostic problem.
   - **Suspected fix:** either (a) let a local declaration shadow a core/global proc in its
     scope (normal lexical shadowing), or (b) emit a clear diagnostic at the *declaration*
     (`local 'open' shadows core proc 'open'`) rather than a confusing type error at a later
     assignment. Likely in `semantic/` symbol resolution. **Deferred** — worked around by
     renaming to `live`; low frequency, revisit if it bites again.

4. **An opaque handle is consumed when passed into a non-extern proc — can't factor socket I/O
   into helpers. DEFERRED (worked around).**
   Passing `conn: socket` into a plain `proc` (e.g. a `send_str(conn, s)` writer) consumes it, so
   any later use of `conn` errors `use of consumed handle 'conn'`. There's no way to declare a
   *borrowing* opaque param for a non-extern proc. Externs borrow fine (`net_send(s, …)` doesn't
   consume), which is why the echo loop worked — but you can't write your own borrowing helper.
   - **Impact:** all socket writes had to be inlined into `main`; response logic couldn't be
     factored into `serve_file`/`send_*` procs.
   - **Suspected fix:** a read-only borrow mode for opaque params on non-extern procs (the callee
     promises not to consume), mirroring how extern opaque in-params already borrow. `semantic/`.
   - Worked around by inlining; revisit when structuring a larger server (routing/handlers).

6. **No logical `||` / `&&` operators. ✅ FIXED.**
   `if (a == 1 || b == 1)` used to fail to parse (`Expected ')' after if condition`); same for `&&`.
   Both now exist, yielding int 0/1 (arche has no bool, like comparisons). The server's OR
   workaround (`allowed := is_get + is_head`) and nested-`if` ANDs are gone — now
   `if (is_get == 0 && is_head == 0)` / `if (is_get == 1 || is_head == 1)`.
   - **Eager, not short-circuit — and that's correct here:** arche expressions have no side effects
     (funcs are pure; procs aren't expressions) and no traps (OOB and divide-by-zero don't fault),
     so eager evaluation is *behaviorally indistinguishable* from short-circuit. Codegen normalizes
     each operand to i1 (`icmp ne … 0`), combines with `and`/`or`, zext to i32. If expressions ever
     gain effects/traps, upgrade to branch+phi short-circuit.
   - **Impl:** `lexer` (`&&`/`||` tokens, single `&`/`|` is an error), `cst.h` (`OP_AND`/`OP_OR`),
     `lower/lower.c` (`cst_tok_to_op`), `parser/parser.c` (`binop_prec`: `||`<`&&`<comparisons<`+ -`
     <`* /`), `semantic/tycheck.c` (int result), `codegen/codegen.c` (the i1-combine block).
   - **Tests:** `tests/unit/language/operators/logical_basic.arche` (truth table),
     `logical_precedence.arche` (`1 || 0 && 0` == 1; comparisons bind tighter). Suite 325/325 green.

5. **No hashmap / string-keyed map — MIME and routing want one. NOTED (acceptable for now).**
   `mime_by_ext` is a linear `streq` if-chain; a route table would be the same. Fine at this scale.
   A real `stdlib/map` (string-keyed) is the proper fix and is needed before Milestone D routing.

## Lessons (server-side, not arche bugs)

- One `recv` per request (request line + headers must fit ~8 KB) and one read per file (≤ 256 KB):
  demo simplifications, not language limits. A production server would loop `recv` until
  `\r\n\r\n` and stream the body in chunks.
- Kept everything in one `.arche` file: local-module `#import` resolution (importing a sibling
  `src/http.arche`) was not exercised — `#import` is used for stdlib modules. Worth confirming
  whether a project-local module resolves, before splitting a larger server across files.

- `printf` is buffered (per net-demo FINDINGS #6): the `listening on :PORT` line is lost if the
  server is killed before flush. Use `print()` for startup/liveness messages that must appear
  immediately. (Will switch the startup banner to a flushed write.)
