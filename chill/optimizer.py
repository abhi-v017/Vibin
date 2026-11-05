"""IR optimizer: a pipeline of small, independent PASSES.

Every pass takes one IRFunction, rewrites it in place, and returns True if it
changed anything. The pipeline repeats all passes until nothing changes (a
"fixed point"), because one pass often unlocks another:

    store x,5 ; t=load x ; u=t+1 ; print u
      forward_stores   -> t = 5
      fold_constants   -> u = 6  -> print 6
      dead_code        -> removes the now-unused t, u, and the store

Passes
  forward_stores       within a block, replace `load x` with the last stored value
  fold_constants       evaluate operations on constants; propagate copies
  fold_branches        `branch yes ? A : B`  ->  `jump A`
  remove_unreachable   delete blocks that can never run
  remove_unused_slots  delete variables that are never read
  eliminate_dead_code  delete pure instructions whose result is never used

Safety rule: the optimized program must print EXACTLY what the unoptimized one
does. The end-to-end tests run every program both ways and compare.
"""
import copy

from .ir import BinOp, Branch, Const, Copy, Jump, Load, Store, Temp, UnOp
from .typesys import DECIMAL, NUMBER

_NOT_FOLDABLE = object()   # sentinel: "can't compute this at compile time"


def _wrap64(value):
    """Wrap an int to signed 64-bit, matching the machine's overflow behavior."""
    return ((value + 2**63) % 2**64) - 2**63


def fold_binop(op, a, b, operand_type):
    """Compute `a op b` at compile time, or return _NOT_FOLDABLE.

    Division by zero is deliberately NOT folded, so the program still fails
    at runtime exactly as it would unoptimized. Integer division truncates
    toward zero (like the CPU's `sdiv`), unlike Python's `//`.
    """
    if op in (">", "<", ">=", "<=", "==", "!="):
        return {">": a > b, "<": a < b, ">=": a >= b,
                "<=": a <= b, "==": a == b, "!=": a != b}[op]
    if operand_type == NUMBER:
        if op == "+": return _wrap64(a + b)
        if op == "-": return _wrap64(a - b)
        if op == "*": return _wrap64(a * b)
        if op == "/":
            if b == 0:
                return _NOT_FOLDABLE
            quotient = abs(a) // abs(b)
            return _wrap64(-quotient if (a < 0) != (b < 0) else quotient)
    if operand_type == DECIMAL:
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        if op == "/" and b != 0:
            return a / b
    return _NOT_FOLDABLE


# ----------------------------------------------------------------------
# Passes
# ----------------------------------------------------------------------

def forward_stores(func):
    """Store-to-load forwarding inside each basic block.

    After `store x, v`, a later `t = load x` in the SAME block must equal v,
    so it becomes `t = v`. Only within a block (no assumptions across jumps).
    Safe across calls because recipes can't touch each other's variables.
    """
    changed = False
    for block in func.blocks:
        known = {}
        for i, instr in enumerate(block.instrs):
            if isinstance(instr, Store):
                known[instr.slot] = instr.value
            elif isinstance(instr, Load) and instr.slot in known:
                block.instrs[i] = Copy(instr.dest, known[instr.slot])
                changed = True
    return changed


def fold_constants(func):
    """Constant folding + constant/copy propagation.

    Temps are single-assignment, so once we learn `t = 5` (or `t = u`) we can
    replace every use of t. Operations whose inputs are all constants are
    computed now and replaced by a Copy of the result.
    """
    changed = False
    known = {}   # Temp -> Const or Temp it equals

    def substitute(operand):
        return known.get(operand, operand) if isinstance(operand, Temp) else operand

    for block in func.blocks:
        for i, instr in enumerate(block.instrs):
            before = instr.operands()
            instr.map_operands(substitute)
            if instr.operands() != before:
                changed = True

            if isinstance(instr, BinOp) and isinstance(instr.left, Const) \
                    and isinstance(instr.right, Const):
                result = fold_binop(instr.op, instr.left.value, instr.right.value,
                                    instr.left.type)
                if result is not _NOT_FOLDABLE:
                    block.instrs[i] = instr = Copy(instr.dest, Const(result, instr.dest.type))
                    changed = True
            elif isinstance(instr, UnOp) and isinstance(instr.operand, Const):
                value = instr.operand.value
                result = (not value) if instr.op == "not" else (
                    _wrap64(-value) if instr.operand.type == NUMBER else -value)
                block.instrs[i] = instr = Copy(instr.dest, Const(result, instr.dest.type))
                changed = True

            if isinstance(instr, Copy):
                known[instr.dest] = instr.src
    return changed


def fold_branches(func):
    """Turn a branch on a constant condition into a plain jump."""
    changed = False
    for block in func.blocks:
        last = block.instrs[-1] if block.instrs else None
        if isinstance(last, Branch) and isinstance(last.cond, Const):
            target = last.then_label if last.cond.value else last.else_label
            block.instrs[-1] = Jump(target)
            changed = True
    return changed


def remove_unreachable(func):
    """Delete blocks that cannot be reached from the entry block."""
    by_label = {b.label: b for b in func.blocks}
    reachable, stack = set(), [func.blocks[0].label]
    while stack:
        label = stack.pop()
        if label in reachable:
            continue
        reachable.add(label)
        stack.extend(by_label[label].successors())
    kept = [b for b in func.blocks if b.label in reachable]
    changed = len(kept) != len(func.blocks)
    func.blocks = kept
    return changed


def remove_unused_slots(func):
    """Delete variables that are written but never read (and their stores)."""
    loaded = {i.slot for b in func.blocks for i in b.instrs if isinstance(i, Load)}
    changed = False
    for block in func.blocks:
        kept = [i for i in block.instrs
                if not (isinstance(i, Store) and i.slot not in loaded)]
        if len(kept) != len(block.instrs):
            block.instrs, changed = kept, True
    for slot in [s for s in func.slots if s not in loaded]:
        del func.slots[slot]
        changed = True
    return changed


def eliminate_dead_code(func):
    """Delete pure instructions whose result no one uses (repeat to fixpoint)."""
    changed = False
    while True:
        used = {op for b in func.blocks for i in b.instrs
                for op in i.operands() if isinstance(op, Temp)}
        removed = False
        for block in func.blocks:
            kept = [i for i in block.instrs if not (i.pure and i.dest not in used)]
            if len(kept) != len(block.instrs):
                block.instrs, removed = kept, True
        if not removed:
            return changed
        changed = True


PASSES = [forward_stores, fold_constants, fold_branches,
          remove_unreachable, remove_unused_slots, eliminate_dead_code]


def optimize_function(func):
    """Run all passes on one function until nothing changes."""
    while any([p(func) for p in PASSES]):   # list: run every pass each round
        pass


def optimize(program):
    """Return an OPTIMIZED COPY of an IRProgram (the original is untouched,
    so the UI can show before/after)."""
    program = copy.deepcopy(program)
    for func in program.functions:
        optimize_function(func)
    return program
