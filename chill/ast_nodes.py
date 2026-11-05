"""AST node definitions for Chill.

An AST (Abstract Syntax Tree) is the tree form of a program. Each class below
is one kind of node. The parser builds these; later stages (type checker, IR
builder) walk them.

Every node carries `line` and `column` so later stages can report errors at
the exact place in the user's source code.
"""
from dataclasses import dataclass, fields
from typing import Any, List


@dataclass(kw_only=True)
class Node:
    """Base class for every AST node. Stores the source position."""
    line: int = 0
    column: int = 0
    type: Any = None   # filled in by the type checker for expressions


# ----------------------------------------------------------------------
# Expressions: things that produce a value
# ----------------------------------------------------------------------

@dataclass
class NumberLit(Node):
    """A number literal such as `20` or `3.5`. `value` is an int or float."""
    value: Any


@dataclass
class StringLit(Node):
    """A text literal such as "hello" (without the quotes)."""
    value: str


@dataclass
class BoolLit(Node):
    """`true` or `false`."""
    value: bool


@dataclass
class Variable(Node):
    """A use of a variable, e.g. the `age` in `say age`."""
    name: str


@dataclass
class UnaryOp(Node):
    """A one-operand operation. `op` is "-" (negate) or "not"."""
    op: str
    operand: Node


@dataclass
class BinaryOp(Node):
    """A two-operand operation, e.g. `1 plus 2`.

    `op` is one of: + - * / > < >= <= == != and or
    """
    op: str
    left: Node
    right: Node


@dataclass
class Call(Node):
    """A recipe (function) call, e.g. `double(21)`."""
    name: str
    args: List[Node]


# ----------------------------------------------------------------------
# Statements: things that DO something (no value)
# ----------------------------------------------------------------------

@dataclass
class MakeStmt(Node):
    """Create a new variable:  make age be 20"""
    name: str
    value: Node


@dataclass
class ChangeStmt(Node):
    """Update an existing variable:  change age to 21"""
    name: str
    value: Node


@dataclass
class SayStmt(Node):
    """Print a value:  say age plus 1"""
    value: Node


@dataclass
class IfStmt(Node):
    """if / otherwise / done. `else_body` is an empty list if no `otherwise`."""
    condition: Node
    then_body: List[Node]
    else_body: List[Node]


@dataclass
class WhileStmt(Node):
    """while <condition> ... done"""
    condition: Node
    body: List[Node]


@dataclass
class Param(Node):
    """One recipe parameter with its declared type:  x as number"""
    name: str
    type_name: str


@dataclass
class RecipeDef(Node):
    """Function definition:  recipe double(x as number) gives number ... done

    `return_type` is None when the recipe gives nothing back.
    """
    name: str
    params: List[Param]
    return_type: Any
    body: List[Node]


@dataclass
class GiveBackStmt(Node):
    """Return from a recipe:  give back x times 2. `value` may be None."""
    value: Any  # Node or None


@dataclass
class ExprStmt(Node):
    """An expression used as a statement. Only calls are allowed, e.g. `greet()`."""
    expr: Node


@dataclass
class Program(Node):
    """The root of the tree: the whole file as a list of statements."""
    statements: List[Node]


# ----------------------------------------------------------------------
# Debug helper
# ----------------------------------------------------------------------

def dump(node, indent=0):
    """Return a readable, indented text drawing of an AST.

    Works generically for every node type by inspecting its dataclass fields,
    so new node classes get printed without extra code.

    Args:
        node: a Node, or a list of Nodes.
        indent: current indentation level (used by the recursion).

    Returns:
        A multi-line string.
    """
    pad = "  " * indent
    if isinstance(node, list):
        return "\n".join(dump(n, indent) for n in node)
    if not isinstance(node, Node):
        return f"{pad}{node!r}"

    scalars, children = [], []
    for f in fields(node):
        if f.name in ("line", "column"):
            continue
        value = getattr(node, f.name)
        if f.name == "type" and value is None:
            continue
        if isinstance(value, Node) or (isinstance(value, list) and value
                                       and isinstance(value[0], Node)):
            children.append((f.name, value))
        else:
            scalars.append(f"{f.name}={value!r}")

    lines = [f"{pad}{type(node).__name__} " + " ".join(scalars)]
    for name, child in children:
        lines.append(f"{pad}  {name}:")
        lines.append(dump(child, indent + 2))
    return "\n".join(l.rstrip() for l in lines)
