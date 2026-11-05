# 04. Interview Prep: Q&A on the Chill Compiler

Answers are written in first person, ready to say out loud, and tied to this codebase. Practise the **60-second pitch** and the **demo script** first.

---

## 60-second pitch

> "I built a casual, English-like programming language called Chill, and a compiler for it from scratch in Python. It goes lexer, parser, type checker, my own three-address IR, an optimizer with six passes, and then LLVM code generation, so it produces real native code, not an interpreter. I wrote a FastAPI backend and a React playground that shows every stage, including the IR before and after optimization. It has 100 tests, and I check the optimizer by running every program with and without it and requiring identical output. One interesting bug: integer division by zero printed garbage, because it's undefined behavior in LLVM, so I added an explicit check in code generation."

## 3-minute demo script

1. Open the playground → pick **Hello, Chill** → Run. ("Source to native code, in memory.")
2. **Tokens** tab: "The lexer. Note `is more than` is one token."
3. **AST** tab: "The parser's tree; deeper means evaluated first."
4. Pick **Optimizer demo** → **IR vs Optimized** tab: "Instruction count drops; constants folded, the dead branch is gone."
5. Pick **Friendly errors** → show the "Did you mean `counter`?" message and that all errors are reported together.
6. **LLVM IR** tab: "This is what LLVM turns into machine code."

---

## A. Big picture

**Q: Walk me through what happens when I press Run.**
The React app POSTs the code to `/api/compile`. FastAPI calls `compile_source()`, which runs the lexer, parser, type checker, IR builder, optimizer, and code generator, and returns every stage's output. If compilation succeeds, a subprocess re-runs the program with a 5-second timeout and the captured output comes back with the stages.

**Q: Compiler or interpreter? How do you know?**
It's a compiler: it translates the whole program to LLVM IR and then machine code before running. An interpreter would walk the tree and execute it directly. I can show both a JIT run and a native executable built with `-o`.

**Q: Why did you build this?**
To understand what languages and tools like linters, ML compilers, and DSL runtimes do under the hood, and to have a finished, tested system rather than a half-built one.

**Q: Why a casual language?**
The pipeline is identical for any language, so the casual syntax is only the front end. It gave me a memorable demo and forced real design problems like multiword operators (`is more than`) and friendly errors.

---

## B. Lexer

**Q: What does the lexer do and why is it separate?**
It converts characters into tokens (type, text, line, column, value), so the parser never worries about whitespace, comments, or digit-by-digit number reading. Separation keeps each stage small and testable.

**Q: How do you handle `is more than` as one operator?**
Before reading a single word, the lexer tries regexes built from each phrase, like `is[ \t]+more[ \t]+than\b`, longest phrase first. The `\b` prevents a variable like `island` from being split into `is` + `land`.

**Q: Why emit NEWLINE tokens?**
There are no semicolons, so a line break ends a statement. Blank lines collapse into one token.

**Q: What's the lexer's complexity?**
Linear in input size. Each word start tries a fixed number (eight) of phrase patterns, so it's still O(n).

**Q: How do you get accurate error positions?**
`advance()` updates `line` and `column` as it consumes characters, and every token stores where it started.

---

## C. Parser

**Q: What parsing technique did you use and why?**
Recursive descent: one method per grammar rule. The grammar is LL(1) at the statement level (the first token picks the rule through a dispatch dictionary), so there's no backtracking, and I can give precise errors like "After `make age` I expected `be`".

**Q: How is operator precedence implemented?**
As a chain of methods from weakest to strongest: `or → and → not → comparison → term → factor → unary → call → primary`. Each calls the next-stronger one first, so `times` binds tighter than `plus`.

**Q: How do you get left associativity?**
A shared helper, `_parse_binary_level`, parses `operand (op operand)*` in a `while` loop and folds left, so `10 minus 3 minus 2` becomes `(10 − 3) − 2`. A recursive right-hand call would have produced `10 − (3 − 2)`, which is wrong.

**Q: What's an AST and why not use the tokens directly?**
A tree capturing structure. Tokens are flat; the tree makes grouping explicit, which is what later stages need.

**Q: How do you report a missing `done`?**
`parse_block` receives the opening token. If EOF arrives first, the error points at the *opener* ("This `while` never gets closed"), which is where the user needs to look.

**Q: How would you add a new statement, like `repeat 3 times`?**
Add tokens and keywords, an AST node, a `parse_repeat` method plus a dispatch entry, then `visit_RepeatStmt` in the analyzer and `stmt_RepeatStmt` in the IR builder (it can lower to a counter and `while`).

---

## D. Type checker

**Q: What does it check that the parser can't?**
Meaning: variables defined before use, types match, conditions are yes/no, call arity and argument types, return types, and that every path through a recipe returns.

**Q: What's a symbol table here?**
A chain of `Scope` objects (dict plus parent). Lookup walks outward. Entering an `if`/`while` body creates a child scope; leaving discards it.

**Q: How do recursion and calling recipes before definition work?**
A first pass collects every recipe's signature (`Signature(name, param_types, return_type)`) before any body is checked. That's why recipes need explicit parameter and return types: without them, a recursive call's type would depend on itself.

**Q: How do recipes avoid seeing main's variables?**
`check_recipe` creates `Scope()` with no parent. Variables outside simply aren't visible, and the IR builder mirrors this with fresh scopes.

**Q: How do you check "all paths return"?**
`always_returns(body)`: a `give back` always returns; an `if` counts only if both branches do; a `while` never counts since its body may run zero times.

**Q: Why report multiple errors instead of stopping at the first?**
Better user experience. To avoid cascades I use an `ERROR` type: once something is invalid, anything built on it is silently accepted instead of triggering follow-up errors.

**Q: How does "Did you mean…?" work?**
`difflib.get_close_matches` against the names visible in the current scope, with a similarity cutoff of 0.6.

**Q: Why no implicit number→decimal conversion?**
Simplicity and predictability. Implicit coercion needs promotion rules and a conversion instruction in the IR and codegen. It's a clear future extension.

---

## E. IR

**Q: Why have your own IR instead of going straight to LLVM?**
Trees are hard to optimize, and LLVM IR is verbose and typed. My IR is small and tailored to Chill, which makes optimization passes short, and it decouples the language from the backend so I could add another target.

**Q: What's three-address code?**
Each instruction does one operation with at most two inputs, storing into a temp: `t2 = t1 + 1`. Complex expressions are broken into steps.

**Q: What's a basic block and why does it matter?**
A straight-line instruction sequence with one entry and one terminator (`Jump`, `Branch`, or `Return`). Blocks joined by jumps form the control-flow graph, which is the shape optimizers and LLVM reason about.

**Q: Why single-assignment temps but mutable variable slots?**
Single-assignment temps make propagation globally safe within a function: if `t = 5` anywhere, every use is 5. Source variables can change, so they live in memory-like slots with `Load`/`Store`. That avoids building full SSA (phi nodes, dominance) in the front end.

**Q: How do you implement `and` / `or` with short-circuiting?**
Store the left value in a hidden slot. For `and`, branch on it: if false, jump to `end`; if true, evaluate the right side in its own `rhs` block, store it, and jump to `end`. At `end`, load the slot. The right side's calls run only when needed, and my `logic.chill` test proves it by printing "evaluated" only when expected.

**Q: What happens to code after `give back`?**
`emit()` sees the block is already terminated and starts a fresh unreachable block. The optimizer's unreachable-block pass removes it.

**Q: Why unique slot names like `x.0`, `x.1`?**
Two sibling `if` blocks can both `make y`, even with different types. Unique names keep their slots separate.

---

## F. Optimizer

**Q: What optimizations do you perform?**
Six passes: store-to-load forwarding (within a block), constant folding and propagation, branch folding, unreachable-block removal, unused-slot removal, and dead-code elimination.

**Q: Why run them in a loop?**
Passes enable each other. Forwarding exposes a constant; folding computes it; dead-code elimination removes the leftovers. I loop until a full round changes nothing (a fixed point). Termination is guaranteed because every change removes or simplifies instructions.

**Q: How do you know the optimizer is correct?**
Every end-to-end program runs optimized and with `-O0` and must produce byte-identical output. I also unit-test the tricky cases.

**Q: What edge cases did you handle in constant folding?**
64-bit wrap-around for `number` arithmetic, integer division truncating toward zero (CPU `sdiv` semantics, not Python's floor), and never folding division by zero so the runtime behavior is preserved.

**Q: Why is forwarding only within a block?**
Across blocks I'd need data-flow analysis (merging values from several predecessors), which is what SSA or reaching-definitions provide. It's the main optimizer limitation and a good next step.

**Q: LLVM already optimizes. Why do you?**
Two reasons: it demonstrates the technique, and Chill-level knowledge can enable things LLVM can't see. To be honest, I don't run LLVM's own IR pass pipeline yet; adding `mem2reg` and friends through `llvmlite` would be the natural next step.

**Q: Complexity?**
Each pass is linear in IR size; the loop runs a small number of rounds in practice.

---

## G. LLVM and code generation

**Q: What is LLVM IR and why use it?**
A typed, low-level, SSA-based representation that LLVM compiles to machine code for many CPUs. I translate once and get native code without writing per-CPU backends.

**Q: How do you map Chill to LLVM?**
Types: `number→i64`, `decimal→double`, `yesno→i1`, `text→i8*`. Variables become `alloca` slots (all in the entry block so loops don't grow the stack) accessed with `load`/`store`. Blocks map one-to-one, jumps become `br`, and `say` becomes a `printf` call with a format chosen by type.

**Q: Why declare all functions before defining them?**
So any recipe can call any other, including forward calls and recursion.

**Q: Why prefix recipe names with `chill_`?**
A user recipe named `printf` or `exit` would otherwise collide with C library functions.

**Q: Tell me about the divide-by-zero bug.**
`say 1 divided by z` with `z = 0` printed a huge number. Integer division by zero is *undefined behavior* in LLVM, so the optimizer is free to turn it into poison. The fix was to emit an explicit check before every integer division: if the divisor is zero, print "Runtime error: you divided by zero." and call `exit(1)`. Now behavior is the same optimized or not, and there are tests for both modes. Lesson: a language's semantics must be defined by the compiler, not left to the backend.

**Q: JIT vs ahead-of-time?**
`--run` JIT-compiles in memory with MCJIT and calls `main`; `-o` emits an object file and links it with the system C compiler. The JIT path needs no linker and is what the playground uses.

**Q: Is there anything you don't guard?**
`INT_MIN / -1` overflow is still undefined in LLVM. Decimal division by zero follows IEEE (`inf`), which is defined.

---

## H. Backend, frontend, and security

**Q: Why does the API run programs in a subprocess?**
The JIT runs machine code inside the host process. An infinite loop or crash would take the API down. A child process can be killed on timeout (5 s), and I cap output at 20,000 characters.

**Q: Is it safe to host publicly?**
Not as is. There's no memory limit, filesystem or network isolation, or rate limiting. For public hosting I'd run each job in a container or gVisor sandbox with resource limits, behind a queue.

**Q: How do you stop huge inputs?**
Pydantic's `max_length=20000` on `code` returns HTTP 422 automatically.

**Q: Why return all stages in one response?**
The UI's tabs render different parts of the same result, so switching tabs needs no extra request, and the CLI and API share one `compile_source()`.

**Q: Why Vite's proxy?**
In development the browser talks to one origin (`:5173`), and Vite forwards `/api` to FastAPI. No CORS configuration is needed, though the backend also whitelists the Vite origin.

**Q: How would you improve the editor?**
Swap the textarea for Monaco or CodeMirror, add syntax highlighting, inline error squiggles from the `line`/`column` the API already returns, and an interactive AST tree.

---

## I. Testing and quality

**Q: How is it tested?**
100 tests: lexer, parser, analyzer, and optimizer units; end-to-end programs with expected output run in both optimizer modes; and API tests for stages, flags, timeout, runtime error, and size limit.

**Q: How do you test error messages?**
Each rule has a failing-program test that asserts the message text and sometimes the line/column.

**Q: Best test you wrote?**
`logic.chill` with a side-effecting function, which proves short-circuit evaluation by what gets printed, and the parametrized optimized-vs-unoptimized run, which acts as an oracle for the optimizer.

---

## J. Trade-offs and "what would you change?"

**Q: What are the biggest limitations?**
No text concatenation or comparison, no number/decimal mixing, a block-local optimizer, and no sandbox hardening.

**Q: What would you build next, in order?**
1. Text runtime (strings with allocation) so `plus` can join text.
2. Run LLVM's own optimization passes via `llvmlite`.
3. SSA conversion and cross-block optimizations.
4. Arrays and a `repeat N times` loop.
5. Containerized execution and a Monaco editor.

**Q: What would you do differently?**
Add a `Span` type (start/end) instead of a single position so errors can underline whole expressions, and design text as a first-class type from the start.

**Q: How did you decide scope?**
Fixed the language small first (variables, math, control flow, recipes, print), finished every stage end to end, and wrote down non-goals so I could ship a complete, tested system.

---

## K. Rapid-fire facts to remember

- Stages: lexer → parser → analyzer → IR builder → optimizer → codegen → run.
- Errors: `CompileError` (first problem) vs `CompileErrors` (all problems).
- Precedence chain: or, and, not, comparison, term, factor, unary, call, primary.
- IR instructions: Copy, BinOp, UnOp, Load, Store, Call, Print, Jump, Branch, Return.
- Optimizer passes: forward_stores, fold_constants, fold_branches, remove_unreachable, remove_unused_slots, eliminate_dead_code.
- LLVM types: i64, double, i1, i8*.
- Limits: 5 s timeout, 20,000-character source and output caps.
- Tests: 11 lexer + 28 parser + 28 analyzer + 9 optimizer + 15 e2e + 9 API = 100.
