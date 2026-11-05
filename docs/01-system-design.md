# 01. System Design

## 1. What this is

**Chill** is a small, casual, English-like programming language, plus a compiler for it written from scratch in Python, plus a web playground.

```
make age be 20
say age plus 1
if age is more than 18
  say "you're an adult"
done
```

The compiler turns this into **LLVM IR** and then into either a JIT-run program or a native executable.

**Goals**
- Implement every classic compiler stage by hand: lexer, parser, type checker, IR, optimizer, code generator.
- Produce real machine code through LLVM, not an interpreter.
- Friendly, human error messages with source positions.
- A web UI that makes each stage visible.

**Non-goals (deliberately out of scope)**
- Classes, generics, modules, a standard library, garbage collection.
- Text concatenation/comparison (needs a runtime with memory management).
- Production-grade sandboxing of untrusted code.

## 2. Use cases

| Who | Use |
|---|---|
| Learner | Run the CLI with `--tokens --ast --ir --opt-ir --llvm` to see each stage's output |
| Interviewer / demo | Open the playground, run an example, show IR before/after the optimizer |
| Language designer | The pipeline is reusable: change the grammar and keep the backend |
| Beginner programmer | Casual syntax with friendly errors (`Did you mean counter?`) |

## 3. Architecture

```
┌──────────────────────────┐         ┌───────────────────────────────────┐
│ React (Vite) :5173       │  JSON   │ FastAPI :8000                     │
│  editor · tabs · diff    │◄───────►│  POST /api/compile                │
└──────────────────────────┘         │   ├─ compile_source()  in-process │
                                     │   └─ run_program()  SUBPROCESS    │
                                     └───────────────┬───────────────────┘
                                                     │ imports
                             ┌───────────────────────▼───────────────────┐
                             │ chill/  (the compiler package)            │
                             │ Lexer→Parser→Analyzer→IRBuilder→Optimizer │
                             │              →CodeGen→(JIT | cc link)     │
                             └───────────────────────────────────────────┘
```

Three layers with one rule: **each layer depends only on the one below it.** The UI knows nothing about compilers; the API knows nothing about parsing; the compiler knows nothing about HTTP.

## 4. The compilation pipeline

| # | Stage | File | Input → Output | Fails with |
|---|---|---|---|---|
| 1 | Lexer | `lexer.py`, `tokens.py` | text → `list[Token]` | `CompileError` |
| 2 | Parser | `parser.py`, `ast_nodes.py` | tokens → AST (`Program`) | `CompileError` |
| 3 | Type checker | `analyzer.py`, `typesys.py` | AST → same AST, annotated with `.type` | `CompileErrors` (all of them) |
| 4 | IR builder | `ir_builder.py`, `ir.py` | typed AST → `IRProgram` | (never, by construction) |
| 5 | Optimizer | `optimizer.py` | `IRProgram` → optimized copy | (never) |
| 6 | Code generator | `codegen.py` | IR → LLVM IR text | (never) |
| 7 | Runner | `runner.py` | LLVM IR → output / executable | runtime errors |

`compiler.py::compile_source()` chains stages 1-6 and returns a `CompileResult` holding every intermediate product. The CLI and the API both call it, so they can never disagree.

### Worked example

Source: `make age be 20` / `say age plus 1`

**Tokens**
```
MAKE IDENT(age) BE NUMBER(20) NEWLINE SAY IDENT(age) PLUS NUMBER(1) NEWLINE EOF
```
**AST**
```
Program
  MakeStmt name='age'   (value: NumberLit 20)
  SayStmt               (value: BinaryOp '+' (Variable age, NumberLit 1))
```
**IR** (three-address code; `age.0` is a variable *slot*)
```
store age.0, 20
t1 = load age.0
t2 = t1 + 1
print t2
```
**Optimized IR**: forwarding turns `t1` into `20`, folding turns `t2` into `21`, dead code removal deletes the rest:
```
print 21
```
**LLVM IR** (simplified): one `printf` call with the constant `21`, then `ret i32 0`.

## 5. Data model

**Token**: `type`, `text`, `line`, `column`, `value` (the parsed int/float/string).

**AST nodes**: one `@dataclass` per construct, all inheriting `Node(line, column, type)`.
- Expressions: `NumberLit, StringLit, BoolLit, Variable, UnaryOp, BinaryOp, Call`
- Statements: `MakeStmt, ChangeStmt, SayStmt, IfStmt, WhileStmt, RecipeDef, GiveBackStmt, ExprStmt`
- `Param` and `Program` complete the set.

**IR**
- Operands: `Const(value, type)` and `Temp(name, type)`, both immutable (hashable, usable as dict keys).
- Instructions: `Copy, BinOp, UnOp, Load, Store, Call, Print` plus terminators `Jump, Branch, Return`.
- `Block(label, instrs)` always ends in exactly one terminator; `IRFunction` has `blocks[0]` as entry; top-level code lives in a function named `<main>`.
- **Temps are single-assignment**; **variables live in named slots** (`x.0`, `x.1`, ...) accessed via `Load`/`Store`.

Each instruction class declares `operand_fields`, `pure`, and `is_terminator`, so optimizer passes work generically instead of with a giant `if/elif` per instruction.

## 6. Error handling design

| Class | Raised by | Carries | Behaviour |
|---|---|---|---|
| `CompileError` | lexer, parser | message, line, column | Stops at the first problem |
| `CompileErrors` | analyzer | list of `CompileError` | Collects **all** problems in one pass |

`CompileError.pretty()` prints the source line with a `^` under the problem. The analyzer uses an `ERROR` placeholder type so one mistake doesn't cascade into five follow-up errors, and `difflib.get_close_matches` powers "Did you mean ...?" hints.

## 7. Execution model and safety

- **Compiling** is pure text processing and runs in the API process.
- **Running** executes machine code, so a bad program (infinite loop, crash) could kill the host. `run_program()` therefore launches `python -m chill file --run` in a **subprocess** with a 5-second timeout and truncates output at 20,000 characters.
- Integer division emits an explicit zero check. Without it, `sdiv x, 0` is *undefined behavior* in LLVM and the optimizer may turn it into garbage. With it, every run prints `Runtime error: you divided by zero.` and exits with code 1.

> Not production-grade: there is no memory limit, container, or per-user rate limiting. Don't expose the run endpoint publicly without adding those.

## 8. API contract

`POST /api/compile`
```json
{ "code": "say 1", "optimize": true, "run": true }
```
Response on success:
```json
{
  "ok": true, "errors": [],
  "tokens": [{"type": "SAY", "text": "say", "line": 1, "column": 1}],
  "ast": "Program\n  ...", "ir": "...", "optimizedIr": "...", "llvm": "...",
  "stats": {"before": 5, "after": 2},
  "output": "1\n", "runError": null
}
```
Response on failure: `{"ok": false, "errors": [{"message", "line", "column", "pretty"}]}`.

Limits: source ≤ 20,000 chars (HTTP 422 otherwise). `GET /api/health` returns `{"status":"ok"}`.

## 9. Frontend design

Single-page React app, no state library: `App.jsx` holds `code`, `optimize`, `result`, `tab`, `loading`. `api.js` is the only file that calls `fetch`. `Results` renders one of five tabs from the same response object, so switching tabs never triggers a request. Vite proxies `/api` to port 8000 in development, which avoids CORS entirely (the backend also whitelists `localhost:5173`).

## 10. Testing strategy (100 tests)

| Level | File | What it proves |
|---|---|---|
| Unit | `test_lexer.py` (11) | tokens, phrase matching, positions, errors |
| Unit | `test_parser.py` (28) | statements, precedence, associativity, error messages |
| Unit | `test_analyzer.py` (28) | scopes, types, arity, return paths, multiple errors |
| Unit | `test_optimizer.py` (9) | folding, forwarding, branch folding, DCE, no folding of `/ 0` |
| End-to-end | `test_e2e.py` (15) | 6 real programs, each run **optimized and unoptimized** with identical expected output |
| API | `test_api.py` (9) | stages returned, timeout, runtime error, size limit |

The key idea: **optimizer correctness = same output with and without it.**

## 11. Key design decisions

| Decision | Why | Trade-off |
|---|---|---|
| Hand-written lexer/parser | Learn internals, control error messages | More code than a parser generator |
| Static types with explicit param/return types | Recursion can be checked without inference | Slightly more typing for the user |
| Own IR before LLVM | Easy language-specific optimization, clean separation | Extra stage to maintain |
| Variables as slots (`Load`/`Store`) | Avoids SSA/phi complexity in the builder | Optimizer is block-local for variables |
| Single-assignment temps | Propagation is globally safe in a function | Needs slots for `and`/`or` results |
| Short-circuit via hidden slot + blocks | Correct semantics for calls with side effects | More blocks emitted |
| JIT in a subprocess | Isolation from crashes and loops | Process start cost per run |
| One `compile_source()` | CLI and API stay in sync | None significant |

## 12. Known limitations and future work

- No text joining or comparison; no implicit `number`→`decimal` conversion.
- Optimizer propagates variable values only **within a basic block** (no global data-flow analysis, no loop optimizations, no SSA).
- We do not run LLVM's own IR pass pipeline (e.g. `mem2reg`); adding it via `llvmlite` is a natural next step.
- `INT_MIN / -1` overflow is not guarded. Decimal division by zero follows IEEE rules (`inf`).
- Very deeply nested expressions can hit Python's recursion limit in the parser.
- Frontend editor is a textarea; the AST is shown as text rather than an interactive tree.
- Ideas: arrays, a `repeat N times` loop, text runtime, SSA conversion, a language server.

## 13. Folder map

```
chill/
├── chill/        compiler package (lexer … runner, CLI)
├── backend/      FastAPI app
├── frontend/     React + Vite playground
├── tests/        unit, e2e, API tests + tests/programs/*.chill with .expected
├── examples/     sample programs
└── docs/         these documents
```
