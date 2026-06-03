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
- **D — routing** ✅ radix router landed as a stdlib module (`stdlib/router/router.arche`), a
  segment-level compressed trie with `:param` capture + `*` catchall. Building it surfaced and
  fixed a real codegen bug (finding #7). Not yet wired into `src/main.arche` (still static-file
  path mapping) — the module + its unit test stand on their own.
- **E — concurrency**: not built — the demo is a single-blocking-connection static server by
  design. Concurrency (non-blocking + `poll()` in `runtime/net.c`) is the next real
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

10. **A top-level const before a line comment had its value corrupted. ✅ FIXED.** `B :: 0` followed
    by a line comment then any decl miscompiled — the value read as float ("double 0") and leaked the
    comment text into codegen (`integer constant must have integer type`). Cause: a CST node's
    `length` runs to the next token, so it swallows a trailing comment leaf; both CST→AST builders
    dup the literal's *node span* for its lexeme, and `strchr(lexeme,'.')` then sees a `.` in the
    comment → typed float. Fix: take the literal from its first **token** leaf, not the node span —
    `cv_dup_first_token` (`lower/lower.c`) + `sem_cv_dup_first_token` (`semantic/semantic.c`). Found
    while adding `true`/`false` to core (the first core consts, sitting before a comment). Test:
    `tests/unit/language/types/const_before_comment.arche`. Spec: `2026-06-01-buffer-cap-and-const-comment.md`.

9. **`.cap`/`.length` didn't work on a fixed `char[N]` buffer. ✅ FIXED.** Wanted `net_recv(conn, req,
   req.cap)` instead of repeating `8192`. The size is already tracked (the `string_len` that `buf[i]`
   bounds-checks against) but the field accessor only wired `.length`/`.capacity` for archetypes and
   `arche_array`, not type-7 stack buffers; const-sized arrays aren't possible either (grammar size
   is a Number literal). Fix: a type-7 branch in `codegen/codegen.c` emitting the declared N for
   `cap`/`capacity`/`length`/`max_length` (a fixed array's length == capacity == N; content is
   `strlen`), + `semantic.c` accepting them. Test: `tests/unit/language/types/buffer_cap_length.arche`.
   Used to de-magic the server (`req.cap`, `body.cap`, `method.cap - 1`, `target.cap - 1`).

   *Also this pass (not bugs):* `true :: 1` / `false :: 0` added to `core/core.arche` for readability
   (arche has no `bool`); the server now reads `is_get == false`, `running := true`. The radix router
   (`stdlib/router/router.arche`) was finished — dropped the hand-rolled `node_count` (now
   `i32(insert(...))` gives the slot) and the `seg_bytes` arena (now a `seg :: char[32]` column),
   exercising the array-column fix (#7). The server handler was refactored to a `serve(conn, root)`
   proc with **guard clauses** (early returns; `conn` borrowed, closed once by the loop; `fd`
   auto-drops per path) — enabled by the RAII fix that retired the old "opaque consumed by a proc"
   limitation (#4). 13/13 integration tests still pass.

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

## Limitations found (since fixed / deferred)

8. **A string-literal variable passed to a `char[]` proc parameter crashed. ✅ FIXED.**
   `x := "hello"` stores `x` as a bare `i8*` (type 2). Passing it to `f(s: char[])` (lowered as
   `arche_array*`) passed the raw pointer **as** the struct — the callee read the string bytes as
   `{ptr,len,cap}`, got a garbage data pointer, and faulted in `strlen` ("stack overflow"). A
   literal passed *directly* (`f("hello")`) and a `char[N]` *buffer* variable both worked; only the
   literal-bound variable broke.
   - **Impl (`codegen/codegen.c`):** the call-arg path now wraps a type-2 string variable in a
     stack `arche_array` for a non-extern `char[]` param (was passing the bare `i8*`); `x :=
     "literal"` now records the literal length in `string_len` (was `-1`) so the wrap carries a
     real size. Spec: `docs/superpowers/specs/2026-06-01-string-var-to-char-param.md`.
   - **Test:** `tests/unit/language/strings/string_var_to_char_param.arche`. Suite 343/343 green.
   - **Found via** the router: its test bound paths to locals (`up := "/users/42"`) before passing
     them to `route_resolve(path: char[])`.

7. **`char[N]` archetype columns were declarable but unusable — insert mis-lowered + column
   under-sized. ✅ FIXED.** Found while building the radix router (D): the natural node layout
   `Node :: arche { seg :: char[32], … }` compiled with a no-op `main` (it was parked in
   `tests/unit/language/known_failures/multidim_varlen.arche`) but **any real use broke**:
   - `insert(Node, "users", 7)` failed to optimize — `@arche_insert_Node` typed the `char[32]`
     param as the element type `i8` and did a single scalar `store`, but the call passes the array
     **pointer** (`'%v' defined with type 'ptr' but expected 'i8'`).
   - The column's struct field was sized `[capacity x i8]` instead of `[capacity * N x i8]`, so the
     per-row stride was 1 byte; a second insert's write overran and corrupted the rest of the
     struct (surfaced as a runtime "stack overflow").
   - Runtime-indexed reads `Node.seg[i]` (loop var `i: i32`) emitted `mul i64 %i, N` without
     widening `%i` to i64 (`'%i' defined with type 'i32' but expected 'i64'`).
   - **Impl (all `codegen/codegen.c`):** struct-layout column element count ×
     `field_total_elements`; `arche_insert_<A>` ABI takes a `char[N]` column by pointer + emits
     `llvm.memcpy` of the whole row (numeric `T[N]` columns keep legacy scalar element-0 init);
     call-site annotates the `char[N]` arg as a pointer; shaped reads coerce both indices to i64
     via `emit_index_i64`. Spec: `docs/superpowers/specs/2026-06-01-array-archetype-columns.md`.
   - **Tests:** `tests/unit/language/arch/char_column.arche` (insert + loop-read + strlen/streq),
     `arch/multi_char_columns.arche` (two char[N] columns, promoted out of `known_failures/`).
     Suite 342/342 green.
   - **Known remaining gap (minor, worked around):** a `char[]` column row passed *directly* as a
     printf vararg still mistypes to i32 — bind it to a local first (`r := Node.seg[0]`). The
     router doesn't hit this (it's 1D — segment text lives in a flat `char[]` arena, not a column).

2. **A local shadowing a core proc name silently mis-resolved — now a clear hard error. ✅ FIXED.**
   Naming a local `open := 1` (intending a loop flag) made `open = 0` fail with
   `assignment: expected 'proc(2)(1)', got 'int'`. The real bug was an *inconsistency*: a **read**
   of `open` resolved to the local (so `open := 1; print(open)` worked), but an **assignment
   target** resolved to the core `open` proc — a silent footgun.
   - **Decision (camp survey):** C/C++/Rust/Go/Swift/Odin allow shadowing (Rust embraces it;
     Odin warns only under opt-in `-vet-shadowing`); **Jai and Zig hard-error** on it. Arche's
     "no hidden behavior" ethos and its Jai-leaning DOD lineage → **hard error**, but scoped to
     the real footgun: a local may not shadow a **callable** (proc/func). Local-vs-local,
     param shadowing, and the `:=` **move-rebind idiom** (`b := strcopy(move b, …)`, which arche
     depends on) stay legal — a blanket no-shadow rule (full Jai) would break that idiom.
   - **Impl:** `semantic/semantic.c` `check_shadows_callable()` (uses `find_known_func`) called at
     every local-binding site (single/multi/out-bindings); new diagnostic **E0116**
     `local_shadows_callable` in `sem_diagnostics.{h,c}`. Message names the clash and says rename.
   - **Test:** `tests/unit/language/shadowing/local_shadows_callable.arche`. Suite 326/326 green.
   - Server still uses `live` (no change needed); `open` would now fail loudly at the declaration.

4. **Opaque handle linearity was branch-insensitive — misdiagnosed, then fixed by RAII. ✅ FIXED.**
   Originally filed as "opaque consumed when passed into a non-extern proc." That was **wrong** —
   passing an opaque into a plain `proc` borrows fine. Re-checking found the real bug: **consume
   tracking was branch-insensitive (function-scope, not flow-sensitive).** A `move`/close inside one
   `if` branch poisoned the binding for the rest of the function — both a false positive
   (`if(e){close(h)} else {…; close(h)}` → bogus `use of consumed handle` in the else) and a false
   negative (`if(e){close(h)}` satisfied must-consume yet leaked on the other path). That's what
   forced the original server to inline everything.
   - **Resolution (design pivot):** rather than hand-track linearity, introduce **destructors /
     RAII**. A `@drop` decorator registers a destructor for an opaque type (`@drop arche_fclose`,
     `@drop net_close`); the compiler auto-calls it at every scope exit for live handles. You stop
     hand-closing entirely, so the branch-poisoning footgun disappears. Consumption (move/return/
     `insert`, or explicitly calling the destructor) suppresses the auto-drop. (`@drop(socket)` /
     `@drop(file)` name the dropped type explicitly at the site.) Conditional consume
     is **all-paths-or-none** (mixed → `consumed on some paths but not others` error), which fixed
     the flow-insensitivity soundly with no runtime drop-flag.
   - **Impact on the server:** `fd` is no longer closed by hand — `arche_fopen_read(path)(fd:)` then
     just use it; auto-drop closes it on every path (404 and 200). Verified: 1500 requests, server
     holds 4 fds (no leak). The old conditional `arche_fclose(move fd)` is now correctly rejected
     as a 'some paths' consume.
   - **Impl (in `/home/curt/Code/arche`):** `@drop` decorator (parser), destructor registry +
     all-paths-or-none branch analysis + must-consume→auto-drop (semantic), auto-drop emission at
     scope exits (codegen), `@drop` on `arche_fclose`/`net_close` (stdlib). Spec:
     `docs/superpowers/specs/2026-05-31-opaque-destructors-raii.md`. Tests:
     `tests/unit/language/drop/`. Also fixed a latent bug found along the way: `if/else` **else
     bodies were silently dropped** by the AST builder + lowerer (they looked for a non-existent
     `SN_ELSE_CLAUSE`). Full suite 330/330.

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

5. **No hashmap — withdrawn; routing uses a radix tree instead. ✅ resolved by a stdlib module.**
   Earlier filed as "blocks routing." A hashmap only pays off at large key counts, which routing
   never reaches — but the better structure for URL routing isn't a linear scan *or* a hashmap, it's
   a **segment-level radix tree** (compressed trie): shared path prefixes, no hash cost, ordered
   precedence (static > param > catchall), and it benchmarks best even for a handful of routes.
   Shipped as `stdlib/router/router.arche` (pure Arche, no heap): a `static pool<TrieNode>` with an
   intrusive first-child/next-sibling index list for fan-out, segment text in a flat `char[]` arena
   (so **no multi-dim storage needed**), `:param`/`*catchall` support, and a `route_resolve(path) ->
   handler_id:int` API the caller dispatches on via `match` (no stored function pointers → no
   indirect-call cost). Test: `tests/unit/language/router/route_resolve.arche` (static + param +
   wildcard + miss + dispatch). The only language gap it exposed was finding #7, now fixed.

## TODO (deferred, low priority)

- **Pool-element destructor teardown (RAII phase 2).** When an opaque-holding archetype lives in a
  `static pool<T>` and a slot is removed (free-list), run the element's `@drop` destructor. Not
  built — and likely a **bad pattern** anyway (pools are for bulk columnar data; RAII handles in a
  pool mixes concerns). Revisit only if a real need appears; the OS reclaims process resources at
  exit regardless.

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
