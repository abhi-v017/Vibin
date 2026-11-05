# 02. Tech Stack: What, Why, How

Every choice below follows the same format: **what it is → why it's here → where it's used → alternatives considered.**

## At a glance

| Layer | Technology | Role |
|---|---|---|
| Language | Python 3.12 | The whole compiler and backend |
| Front end of compiler | Hand-written lexer + recursive descent parser | Text → tokens → AST |
| Data structures | `dataclasses`, `enum` | Tokens, AST, IR |
| Back end of compiler | `llvmlite` (LLVM) | IR → machine code |
| Linking | System C compiler (`cc`/`gcc`/`clang`) | Object file → executable |
| API | FastAPI + Uvicorn + Pydantic | HTTP interface |
| UI | React 18 + Vite | Playground |
| Tests | pytest, httpx (FastAPI test client) | 100 tests |
| CLI | `argparse` | `python -m chill ...` |

---

## Python 3.12
- **What:** The implementation language.
- **Why:** Fast to write and read, which matters when the point is learning compiler structure. Dataclasses and pattern-like dispatch keep AST and IR code short.
- **Where:** Everywhere except the frontend.
- **Alternatives:** Rust/OCaml (stronger for ADTs and pattern matching, but slower to learn and demo); C++ (what LLVM itself uses, far more boilerplate).
- **Cost:** Slower than a native compiler and has a recursion limit that bounds expression nesting depth. Irrelevant at this scale.

## Hand-written lexer
- **What:** A cursor over the source (`peek`, `advance`) with a dispatch loop on the current character. Words are looked up in a `KEYWORDS` dict; multiword operators (`is more than`) are matched first with regexes like `is[ \t]+more[ \t]+than\b`.
- **Why:** Total control over multiword phrases and error messages; shows how lexers really work.
- **Where:** `chill/lexer.py`, `chill/tokens.py`.
- **Alternatives:** `re`-based tokenizer tables, `ply`/`lark`/`ANTLR`. They would work but hide the mechanics, and generic lexers make "casual English" phrases and positioned errors harder.

## Hand-written recursive descent parser
- **What:** One method per grammar rule; rules call each other. Operator precedence comes from a chain of methods (`or → and → not → comparison → term → factor → unary → call → primary`), and one helper `_parse_binary_level` handles all left-associative levels.
- **Why:** The grammar is LL(1) at the statement level (the first token picks the rule), so no backtracking and very readable code. Errors can say exactly what was expected, e.g. "After `make age` I expected `be`".
- **Where:** `chill/parser.py`.
- **Alternatives:** Parser generators (ANTLR, Lark), parser combinators, Pratt parsing. Pratt would shrink the expression code further; recursive descent was chosen because the precedence-per-method structure is easier to explain.

## `dataclasses` and `enum`
- **What:** Standard library tools for plain data classes and named constants.
- **Why:** Tokens, AST nodes, IR instructions, and results are *data*. Dataclasses give constructors, equality, and repr for free, which makes tests like `assert node == NumberLit(20, ...)` trivial. `dump()` walks `dataclasses.fields` so any new node type prints without extra code.
- **Where:** `tokens.py`, `ast_nodes.py`, `ir.py`, `compiler.py`.
- **Gotcha we hit:** A class attribute on a non-dataclass base (`dest = None`) is treated as a *default* by subclasses, which broke field ordering. Fix: don't put defaults on the base.

## Visitor-style dispatch
- **What:** `getattr(self, f"visit_{type(node).__name__}")` routes each node to its handler.
- **Why:** Adds a node type by adding one method; no giant `if isinstance` chains.
- **Where:** `analyzer.py` (`visit_*`), `ir_builder.py` (`stmt_*`, `expr_*`).
- **Alternative:** The classic double-dispatch Visitor with `accept()` methods; more ceremony in Python for no gain.

## Three-address-code IR with basic blocks
- **What:** A flat instruction list grouped into basic blocks, each ending in one terminator.
- **Why:** Trees are awkward to optimize; flat instructions are easy to scan, rewrite, and delete. It also decouples the language from the backend, so a second backend (WebAssembly, x86) could reuse everything above it.
- **Where:** `ir.py`, `ir_builder.py`, `optimizer.py`.
- **Alternatives:** Generate LLVM IR straight from the AST (fewer files, but nowhere to put language-specific optimizations); full SSA (more powerful, needs phi nodes and dominance analysis).

## `llvmlite` (LLVM)
- **What:** A lightweight Python binding to LLVM. `llvmlite.ir` builds LLVM IR; `llvmlite.binding` parses it, verifies it, JIT-compiles it, and emits object code.
- **Why:** Writing machine-code generators per CPU is a huge job. LLVM gives native code for the host CPU (x86-64, ARM) from one IR. It is also the most resume-relevant backend (Rust, Swift, and Clang all use LLVM).
- **Where:** `codegen.py` (IR → LLVM IR text), `runner.py` (JIT, object emission).
- **How:** Type mapping `number→i64`, `decimal→double`, `yesno→i1`, `text→i8*`. Variables become `alloca` slots in the entry block. `print` calls C's `printf`.
- **Alternatives:** Emitting assembly by hand (educational, not portable), WebAssembly (browser-friendly), a bytecode VM (an interpreter, not a compiler), Cranelift/QBE (lighter backends).

## System C compiler (`cc`)
- **What:** Used only for the *final link* when you ask for a native executable (`-o out`).
- **Why:** The linker supplies C's `printf`/`exit` and program startup code. The `--run` path needs none of this because the JIT resolves symbols from the current process.
- **Where:** `runner.build_executable`. We emit position-independent code (`reloc="pic"`) so modern linkers don't warn.

## FastAPI, Uvicorn, Pydantic
- **What:** FastAPI is the web framework, Uvicorn the ASGI server, Pydantic validates request bodies.
- **Why:** A typed request model gives automatic validation (the 20,000-character limit becomes an HTTP 422 for free), automatic docs at `/docs`, and a very small amount of code.
- **Where:** `backend/app.py`.
- **Alternatives:** Flask (simpler, but manual validation), Django (far heavier than needed), a WebAssembly build of the compiler (no server, but a much harder build).

## Subprocess for running programs
- **What:** `subprocess.run([python, "-m", "chill", file, "--run"], timeout=5, capture_output=True)`.
- **Why:** A JIT executes machine code *inside the calling process*; an infinite loop or crash would take the API down. A child process can be killed and its output size capped.
- **Alternatives:** Docker or gVisor per run, `seccomp`, a job queue with workers. Needed before real public hosting.

## React 18 + Vite
- **What:** React renders the UI; Vite is the dev server and bundler.
- **Why:** React was your preferred stack. Vite starts instantly and its `server.proxy` forwards `/api` to FastAPI, so there is no CORS setup in development.
- **Where:** `frontend/src/` (`App.jsx`, `api.js`, `examples.js`, `styles.css`).
- **Alternatives:** Next.js (server rendering isn't needed), Monaco/CodeMirror for a real editor (a good upgrade; kept to a textarea to stay dependency-light).

## pytest and httpx
- **What:** pytest runs tests; FastAPI's `TestClient` uses httpx to call the API without a network.
- **Why:** `@pytest.mark.parametrize` runs each end-to-end program in both optimizer modes with one test function. `monkeypatch` shortens the timeout so the infinite-loop test takes about a second.
- **Where:** `tests/`.

## `argparse`
- **What:** Standard-library CLI parsing.
- **Why:** No dependency needed for a handful of flags (`--tokens --ast --ir --opt-ir --llvm --run -o -O0`).
- **Where:** `chill/__main__.py`.

---

## How the pieces talk (one request, end to end)

1. You press **Run**. `api.js` POSTs `{code, optimize, run}` to `/api/compile`.
2. Vite proxies it to FastAPI; Pydantic validates it.
3. `compile_source()` runs lexer → parser → analyzer → IR builder → optimizer → code generator.
4. If a stage raises `CompileError(s)`, the API returns `{ok:false, errors:[...]}` and React shows them.
5. Otherwise the API starts a subprocess that re-compiles and JIT-runs the program, and captures stdout.
6. The response (all stages + output) returns to React, which renders whichever tab is selected.

## Dependencies you must install

```
Python:  pytest, llvmlite, fastapi, uvicorn, httpx
Node:    react, react-dom, vite, @vitejs/plugin-react
System:  a C compiler (only for `-o` native executables)
```
