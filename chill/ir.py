"""Intermediate Representation (IR): a flat, simple form of the program.

The IR is "three-address code": every instruction does ONE small thing, and
complex expressions are broken into steps using temporaries (t1, t2, ...).

Key design points
  * A program is a list of IRFunctions. Top-level code becomes `<main>`.
  * A function is a list of BASIC BLOCKS: straight-line instruction lists that
    always end in exactly one terminator (Jump / Branch / Return).
  * TEMPS are single-assignment (each is defined once). That makes constant
    propagation and dead-code removal simple and safe.
  * VARIABLES live in named SLOTS accessed with Load/Store (like memory).
    LLVM's own optimizer can later turn slots into registers.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .typesys import TEXT, YESNO


# ----------------------------------------------------------------------
# Operands: the things instructions work on
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Const:
    """A compile-time constant value, e.g. 42, 2.5, "hi", yes."""
    value: Any
    type: str

    def __str__(self):
        if self.type == TEXT:
            return f'"{self.value}"'
        if self.type == YESNO:
            return "yes" if self.value else "no"
        return repr(self.value)


@dataclass(frozen=True)
class Temp:
    """A temporary result, defined by exactly one instruction."""
    name: str
    type: str

    def __str__(self):
        return self.name


# ----------------------------------------------------------------------
# Instructions
# ----------------------------------------------------------------------

class Instr:
    """Base class. Subclasses declare which fields are operands.

    Attributes:
        operand_fields: names of fields holding operands (inputs).
        pure: True if removing the instruction is safe when its result is
              unused (no side effects). Used by dead-code elimination.
        is_terminator: True for Jump / Branch / Return.
        dest: (on subclasses that define a value) the Temp it defines.
    """
    operand_fields = ()
    pure = False
    is_terminator = False

    def operands(self):
        """List of all operand values this instruction reads."""
        return [getattr(self, f) for f in self.operand_fields
                if getattr(self, f) is not None]

    def map_operands(self, fn):
        """Replace every operand `o` with `fn(o)` (used by propagation)."""
        for f in self.operand_fields:
            value = getattr(self, f)
            if value is not None:
                setattr(self, f, fn(value))


@dataclass
class Copy(Instr):
    """dest = src"""
    dest: Temp
    src: Any
    operand_fields = ("src",)
    pure = True

    def __str__(self):
        return f"{self.dest} = {self.src}"


@dataclass
class BinOp(Instr):
    """dest = left <op> right   (op: + - * / > < >= <= == !=)"""
    dest: Temp
    op: str
    left: Any
    right: Any
    operand_fields = ("left", "right")
    pure = True

    def __str__(self):
        return f"{self.dest} = {self.left} {self.op} {self.right}"


@dataclass
class UnOp(Instr):
    """dest = <op> operand   (op: - or not)"""
    dest: Temp
    op: str
    operand: Any
    operand_fields = ("operand",)
    pure = True

    def __str__(self):
        return f"{self.dest} = {self.op} {self.operand}"


@dataclass
class Load(Instr):
    """dest = value stored in variable slot"""
    dest: Temp
    slot: str
    pure = True

    def __str__(self):
        return f"{self.dest} = load {self.slot}"


@dataclass
class Store(Instr):
    """variable slot = value"""
    slot: str
    value: Any
    operand_fields = ("value",)

    def __str__(self):
        return f"store {self.slot}, {self.value}"


@dataclass
class Call(Instr):
    """[dest =] call func(args...)   (dest is None if nothing is returned)"""
    dest: Optional[Temp]
    func: str
    args: List[Any]

    def operands(self):
        return list(self.args)

    def map_operands(self, fn):
        self.args = [fn(a) for a in self.args]

    def __str__(self):
        call = f"call {self.func}({', '.join(map(str, self.args))})"
        return f"{self.dest} = {call}" if self.dest else call


@dataclass
class Print(Instr):
    """Show a value (the `say` statement)."""
    value: Any
    operand_fields = ("value",)

    def __str__(self):
        return f"print {self.value}"


@dataclass
class Jump(Instr):
    """Unconditional jump to a block label."""
    target: str
    is_terminator = True

    def __str__(self):
        return f"jump {self.target}"


@dataclass
class Branch(Instr):
    """Jump to then_label if cond is yes, else to else_label."""
    cond: Any
    then_label: str
    else_label: str
    operand_fields = ("cond",)
    is_terminator = True

    def __str__(self):
        return f"branch {self.cond} ? {self.then_label} : {self.else_label}"


@dataclass
class Return(Instr):
    """Leave the function, optionally with a value."""
    value: Any
    operand_fields = ("value",)
    is_terminator = True

    def __str__(self):
        return "return" if self.value is None else f"return {self.value}"


# ----------------------------------------------------------------------
# Containers
# ----------------------------------------------------------------------

@dataclass
class Block:
    """A basic block: a label plus instructions ending in one terminator."""
    label: str
    instrs: List[Instr] = field(default_factory=list)

    def terminated(self):
        """True once the block's last instruction is a terminator."""
        return bool(self.instrs) and self.instrs[-1].is_terminator

    def successors(self):
        """Labels of the blocks control can flow to from here."""
        if not self.terminated():
            return []
        last = self.instrs[-1]
        if isinstance(last, Jump):
            return [last.target]
        if isinstance(last, Branch):
            return [last.then_label, last.else_label]
        return []


@dataclass
class IRFunction:
    """One function. `params` are (temp_name, type) pairs; `slots` maps each
    variable-slot name to its type. blocks[0] is always the entry block."""
    name: str
    params: List[Tuple[str, str]]
    return_type: str
    blocks: List[Block] = field(default_factory=list)
    slots: Dict[str, str] = field(default_factory=dict)


@dataclass
class IRProgram:
    """All functions. The entry point is the function named `<main>`."""
    functions: List[IRFunction]


def format_ir(program):
    """Render an IRProgram as readable text (for --ir and the UI)."""
    lines = []
    for func in program.functions:
        params = ", ".join(f"{n}: {t}" for n, t in func.params)
        lines.append(f"func {func.name}({params}) -> {func.return_type}")
        for block in func.blocks:
            lines.append(f"  {block.label}:")
            lines.extend(f"    {instr}" for instr in block.instrs)
        lines.append("")
    return "\n".join(lines)
