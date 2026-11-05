# 03. Rebuild Guide: Create This Project From Scratch

Follow the steps in order. Each step lists **what to write**, **the key idea**, and a **checkpoint** that proves it works before you move on. Never start step N+1 with step N red.

Rule of thumb: after every stage, add a way to *see* its output (CLI flag or test). Debugging a compiler is mostly looking at intermediate results.

---

## Step 0. Setup

```
mkdir chill && cd chill
mkdir chill tests examples backend frontend docs
touch chill/__init__.py backend/__init__.py
pip install pytest llvmlite fastapi uvicorn httpx
```
Checkpoint: `python -c "import llvmlite; print(llvmlite.__version__)"` works.

## Step 1. Language reference (design before code)

| Feature | Syntax |
|---|---|
| Create variable | `make age be 20` |
| Update variable | `change age to 21` |
| Print | `say age plus 1` |
| Condition | `if x is more than 5` … `otherwise` … `done` |
| Loop | `while i is less than 3` … `done` |
| Function | `recipe fib(n as number) gives number` … `give back n` … `done` |
| Call | `fib(10)` |
| Comments | `# note` |

Types: `number` (64-bit int), `decimal` (double), `text` (literal only), `yesno` (`true`/`false`, printed `yes`/`no`).
Operators: `plus minus times divided by`, `is more than / is less than / is at least / is at most / is equal to / is not equal to`, `and or not`, unary `minus`.
Rules: variables are block-scoped; re-`make` of a visible name is an error; recipes can't see the main program's variables; recipes can be called before they're defined.

Write 5 example programs *now*; they become your test fixtures.

## Step 2. Tokens and Lexer (`tokens.py`, `lexer.py`, `errors.py`)

**Write**
1. `errors.py`: `CompileError(message, line, column, source)` with `pretty()` printing the source line and a `^` under the column. Later add `CompileErrors(errors)` that wraps a list.
2. `tokens.py`: `TokenType` enum; `Token` dataclass (`type, text, line, column, value`); `KEYWORDS` dict (`make→MAKE`, …); `PHRASES` dict (`"is more than"→GREATER`, `"divided by"→DIVIDE`, `"give back"→GIVE_BACK`, …).
3. `lexer.py`: class `Lexer` with a cursor (`pos, line, column`), `peek()`, `advance()` (updates line/column), and `tokenize()`.

**Key ideas**
- `tokenize()` loops on the current char: spaces skipped; `\n` → `NEWLINE` token (collapse blank lines); `#` skips to end of line; `"` reads a string (error if unterminated); digit → number (a `.` counts only if a digit follows); letter → word; `( ) ,` → single-char tokens; anything else → error.
- `read_word()` tries **phrase regexes first**, longest first, each built as `word1[ \t]+word2[ \t]+…\b`. The trailing `\b` is why `island` is not split into `is` + `land`. Otherwise read one word and look it up with `KEYWORDS.get(text.lower(), IDENT)`.
- Always end with an `EOF` token.

**Checkpoint:** `tokenize("make age be 20")` → `MAKE IDENT BE NUMBER EOF`; tests for phrases, positions, unterminated string. (11 tests)

## Step 3. AST and Parser (`ast_nodes.py`, `parser.py`)

**Write**
1. `ast_nodes.py`: base `@dataclass(kw_only=True) class Node` with `line`, `column`, `type=None`; then one dataclass per construct (see system-design doc §5); `Param`; `Program`; a generic `dump()` using `dataclasses.fields`.
2. `typesys.py` (tiny): `NUMBER, DECIMAL, TEXT, YESNO, NOTHING, ERROR` string constants, `TYPE_NAMES`, `describe_type()` ("a number").
3. `parser.py`: class `Parser(tokens, source)` with helpers `peek, check, advance, match, expect, error, skip_newlines, end_statement`.

**Key ideas**
- `parse_statement()` uses a **dispatch dict** from first-token type to method (`MAKE→parse_make`, …). No backtracking.
- `parse_block(opener, *stoppers)` parses statements until a stopper token (`done`, `otherwise`). If EOF arrives first, raise "This `if` never gets closed", pointing at the **opener** token.
- Expression precedence = a method chain, weakest first: `or → and → not → comparison → term → factor → unary → call → primary`.
- One helper `_parse_binary_level(next_rule, {TokenType: "op"})` implements all left-associative levels:
  ```
  left = next_rule()
  while peek().type in operators:
      op = advance(); right = next_rule()
      left = BinaryOp(op, left, right)
  ```
  The loop is what makes `10 minus 3 minus 2` group as `(10 − 3) − 2`.
- `parse_primary` handles number/text/bool/name/parenthesised expression. `parse_call` turns `name(`…`)` into `Call`.
- Recipes: `parse_recipe` reads `name(p as type, …) [gives type]`; `parse_type` accepts an `IDENT` only where a type is expected, so `number` stays usable as a variable name elsewhere.

**Checkpoint:** `python -m chill file --ast` prints the tree; tests for precedence, associativity, nesting, and each error message. (28 tests)

## Step 4. Type checker (`analyzer.py`)

**Write:** `Scope` (dict + parent, `declare`, `lookup`, `visible_names`), `Signature(name, param_types, return_type)`, `always_returns(body)`, and `Analyzer` with `check(program)`.

**Key ideas**
- **Pass 1** `collect_signatures` records every top-level recipe, so calls work in any order and recursion works.
- **Pass 2** visits statements. `visit(node)` dispatches to `visit_<Class>` and stores the result in `node.type`.
- Each `visit_<expr>` **returns the expression's type**. `visit_BinaryOp` checks operand types (no number/decimal mixing, no text arithmetic, `and/or` need `yesno`).
- `check_block` creates a child `Scope`. `check_recipe` creates a **fresh `Scope()` with no parent**, which is how recipes are denied access to main's variables.
- `always_returns`: any statement that always returns makes the body return; an `if` counts only if **both** branches do; a `while` never counts.
- Errors are **collected**, not raised immediately; `ERROR` type suppresses cascades; `difflib.get_close_matches` adds "Did you mean …?".
- `value_of(node)` rejects calls to recipes that give nothing back when a value is required.

**Checkpoint:** every rule has a passing and a failing test, including "multiple errors collected". (28 tests)

## Step 5. IR definitions (`ir.py`)

**Write:** `Const`, `Temp` (frozen dataclasses); `Instr` base with class attrs `operand_fields`, `pure`, `is_terminator`, and methods `operands()` / `map_operands(fn)`; instruction dataclasses `Copy, BinOp, UnOp, Load, Store, Call, Print, Jump, Branch, Return`; `Block` (`terminated()`, `successors()`); `IRFunction` (`name, params, return_type, blocks, slots`); `IRProgram`; `format_ir()`.

**Key ideas**
- Temps are **single-assignment**; variables are **slots** with `Load`/`Store`.
- `pure=True` (Copy, BinOp, UnOp, Load) means "safe to delete if unused".
- Gotcha: do **not** put `dest = None` on the base class. Dataclass subclasses would inherit it as a default and break field ordering.

## Step 6. IR builder (`ir_builder.py`)

**Write:** `IRBuilder.build(program)`; per-function state (`func, block, temp_n, label_n, slot_n, scopes`); helpers `new_block, new_temp, declare, hidden_slot, lookup, emit, scoped`; `stmt_*` and `expr_*` methods.

**Key ideas**
- `expr_*` returns an **operand**; `stmt_*` returns nothing.
- `emit()` starts a new `dead` block if the current block already ended in a terminator (code after `give back`).
- `if` → blocks `then / else / end` joined by `Branch` and `Jump`; `while` → `cond / body / end` with a back-jump.
- Unique slot names (`x.0`, `x.1`) let sibling scopes reuse a name even with different types.
- **Short-circuit `and`/`or`:** store left in a hidden slot; `Branch` on it to either skip or enter an `rhs` block; the rhs stores its result and jumps to `end`; load the slot.
- Top-level code → function `<main>`. A function that falls off the end gets an implicit `Return` (a default constant for non-`nothing` recipes, which the checker guarantees is unreachable).

**Checkpoint:** `--ir` prints readable IR for every example. (Tested through the optimizer tests and e2e.)

## Step 7. Optimizer (`optimizer.py`)

**Write** six passes, each `pass(func) -> bool changed`, plus `optimize_function` (loop until nothing changes) and `optimize` (**deep copy** first so the UI can show before/after).

| Pass | Idea |
|---|---|
| `forward_stores` | within a block, `load x` after `store x, v` becomes `v` |
| `fold_constants` | evaluate ops whose operands are constants; propagate known temps |
| `fold_branches` | `branch yes ? A : B` → `jump A` |
| `remove_unreachable` | graph search from entry; delete the rest |
| `remove_unused_slots` | drop variables that are never loaded, plus their stores |
| `eliminate_dead_code` | drop `pure` instructions whose result is unused (repeat) |

**Key ideas**
- Passes **enable each other**, hence the fixed-point loop. Run all passes each round: `while any([p(func) for p in PASSES])` (a list, so none is skipped by short-circuiting).
- `fold_binop`: 64-bit wrap-around; integer `/` truncates toward zero (like the CPU), not Python's floor; **never fold division by zero**.

**Checkpoint:** `say 2 plus 3 times 4` → `print 14`; `if true …` loses its dead branch; a loop's counter is *not* folded away. (9 tests)

## Step 8. Code generation (`codegen.py`)

**Write:** `init_llvm()`, `llvm_name()`, class `CodeGen` with `generate`, `declare`, `define`, `emit`, `binop`, `print_value`, `get_string`, `guard_zero_divisor`.

**Key ideas**
- **Declare all functions first, then define bodies**, so recipes can call each other in any order.
- Create one LLVM basic block per IR block (`entry` first). Emit all `alloca`s for slots at the start of the entry block so loops don't grow the stack.
- `Temp` → looked up in a `values` dict; `Const` → `ir.Constant`; text → a deduplicated private global string.
- Pick the instruction by operator **and** operand type (`add` vs `fadd`, `icmp_signed` vs `fcmp_ordered`).
- `print`: `printf` with `%lld\n`, `%g\n`, `%s\n`; `yesno` uses `select` between the strings `yes`/`no`.
- Recipes get a `chill_` prefix so a user recipe named `printf` can't collide with libc; `<main>` becomes `main`.
- **Division guard** (`if divisor == 0 { printf(...); exit(1); unreachable }`). Discovered when `say 1 divided by z` printed a memory address: `sdiv` by zero is undefined behavior in LLVM.

## Step 9. Runner, driver, CLI (`runner.py`, `compiler.py`, `__main__.py`)

- `run_llvm_ir`: `parse_assembly` → `verify` → `create_mcjit_compiler` → `finalize_object` → call `main` through `ctypes` → flush C stdio (`fflush(NULL)`).
- `build_executable`: `emit_object` (with `reloc="pic"`) → link with `cc`.
- `compile_source(source, optimize_ir)` → `CompileResult(tokens, ast, ir, optimized_ir, llvm_ir)`.
- CLI flags: `--tokens --ast --ir --opt-ir --llvm --run -o OUT -O0`. Print `error.pretty()` and exit 1 on failure.

**Checkpoint:** `python -m chill examples/recipe.chill --run` prints `12`; the `-o` executable prints the same.

## Step 10. API (`backend/app.py`)

- `CompileRequest` (Pydantic): `code` (max 20,000 chars), `optimize`, `run`.
- Catch `CompileError` and `CompileErrors` → `{ok:false, errors:[...]}`; else return all stages + `stats` (instruction counts).
- `run_program`: write code to a temp file, run the CLI in a subprocess with `timeout=5`; map timeout, negative return codes (signals), and non-zero exits to a friendly `runError`.
- Tests: all stages returned, flag respected, timeout (monkeypatch it to 1s), divide by zero, oversize → 422.

Run: `uvicorn backend.app:app --reload`; docs at `http://localhost:8000/docs`.

## Step 11. Frontend (`frontend/`)

1. `npm create vite@latest frontend -- --template react`, or copy `package.json` / `vite.config.js` (proxy `/api` → `:8000`).
2. `api.js`: one `compileCode()` function.
3. `App.jsx`: state for code/optimize/result/tab/loading; toolbar (examples, optimize, run); textarea editor; five tabs.
4. Build order: editor + Run + Output → error list → Tokens → AST → IR-vs-Optimized with stats → LLVM → examples dropdown → Ctrl+Enter.

Checkpoint: `npm run build` succeeds; the Optimizer demo example shows a drop in instruction count.

## Step 12. Test matrix (do this alongside, not at the end)

`tests/programs/*.chill` + `*.expected`; `test_e2e.py` parametrizes **program × {optimized, -O0}**. The optimizer is correct iff both modes print identical output.

---

## Troubleshooting log (real problems from this build)

| Symptom | Cause | Fix |
|---|---|---|
| `non-default argument follows default argument` in `ir.py` | `dest = None` on non-dataclass base is inherited as a field default | Remove it from the base |
| `ModuleNotFoundError: chill` when running a script | Package not on `sys.path` | Run from project root or `python -m` / `PYTHONPATH=.` |
| `1 divided by z` printed a huge number | `sdiv` by zero is undefined behavior; LLVM optimizes it into garbage | Explicit zero-check in codegen |
| Linker warns about `DT_TEXTREL` | Object emitted as non-PIC | `create_target_machine(reloc="pic")` |
| Output missing/out of order from JIT | C `printf` buffer not flushed | `fflush(NULL)` after the call |
| Shell dies when stopping servers with `pkill -f` | Pattern matches your own command line | Use PIDs, or `pgrep -f` first |

## Order of work (suggested schedule)

| Week | Steps |
|---|---|
| 1 | 1-2 (design, lexer) |
| 2 | 3 (parser) |
| 3 | 4 (type checker) |
| 4 | 5-6 (IR) |
| 5 | 8-9 (codegen, run) |
| 6 | 7 (optimizer) |
| 7 | 10-11 (API, UI) |
| 8 | 12 + polish, README, demo GIF |
