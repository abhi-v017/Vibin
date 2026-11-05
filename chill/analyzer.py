"""Semantic analysis (the "type checker").

The parser only checks that the program's SHAPE is valid. This stage checks
that it MAKES SENSE:

  * every variable/recipe is defined before use
  * operators get operands of the right types
  * `if`/`while` conditions are yes/no
  * recipe calls have the right number and types of arguments
  * `give back` matches the declared return type, on every path

It also ANNOTATES the tree: every expression node gets `node.type`, which the
IR builder later relies on (so it never has to guess types).

Technique: a Visitor. `visit(node)` dispatches to `visit_<NodeClassName>`.
Scopes are a linked chain of dictionaries (the "symbol table").

Scoping rules of Chill
  * Variables are block-scoped (if/while bodies get their own scope).
  * You cannot re-`make` a name that is already visible (use `change`).
  * Recipes cannot see the main program's variables (no globals): they only
    see their parameters and their own variables.
  * Recipes may only be defined at the top level, and can be called before
    their definition (signatures are collected in a first pass).
"""
from dataclasses import dataclass
from difflib import get_close_matches
from typing import List

from .ast_nodes import RecipeDef, GiveBackStmt, IfStmt
from .errors import CompileError, CompileErrors
from .typesys import (
    DECIMAL, ERROR, NOTHING, NUMERIC, TEXT, YESNO, describe_type,
)

ARITHMETIC = ("+", "-", "*", "/")
ORDERING = (">", "<", ">=", "<=")
EQUALITY = ("==", "!=")
LOGIC = ("and", "or")
OP_WORDS = {
    "+": "plus", "-": "minus", "*": "times", "/": "divided by",
    ">": "is more than", "<": "is less than", ">=": "is at least",
    "<=": "is at most", "==": "is equal to", "!=": "is not equal to",
    "and": "and", "or": "or",
}


@dataclass
class Signature:
    """What the rest of the program needs to know to CALL a recipe."""
    name: str
    param_types: List[str]
    return_type: str


class Scope:
    """One level of the symbol table: names -> types, plus a parent link."""

    def __init__(self, parent=None):
        self.names = {}
        self.parent = parent

    def declare(self, name, type_name):
        """Add a variable to THIS scope."""
        self.names[name] = type_name

    def lookup(self, name):
        """Find a variable's type, searching outward. Returns None if absent."""
        scope = self
        while scope is not None:
            if name in scope.names:
                return scope.names[name]
            scope = scope.parent
        return None

    def visible_names(self):
        """All names visible from here (used for 'did you mean' hints)."""
        names, scope = set(), self
        while scope is not None:
            names |= set(scope.names)
            scope = scope.parent
        return names


def always_returns(body):
    """True if EVERY path through `body` ends in `give back`.

    A statement list always returns if any statement in it always returns.
    A `give back` does; an `if` does only when both branches do; a `while`
    never counts (its body might run zero times).
    """
    for stmt in body:
        if isinstance(stmt, GiveBackStmt):
            return True
        if isinstance(stmt, IfStmt) and stmt.else_body:
            if always_returns(stmt.then_body) and always_returns(stmt.else_body):
                return True
    return False


class Analyzer:
    """Walks the AST, reports problems, and annotates expression types.

    Usage:
        signatures = Analyzer(source).check(program)   # raises CompileErrors
    """

    def __init__(self, source=""):
        self.source = source
        self.errors = []
        self.functions = {}          # recipe name -> Signature
        self.scope = None            # current Scope
        self.current_recipe = None   # Signature of the recipe being checked

    # ------------------------------------------------------------------
    # Entry point and helpers
    # ------------------------------------------------------------------

    def check(self, program):
        """Analyze a whole Program.

        Returns:
            dict of recipe name -> Signature.
        Raises:
            CompileErrors: if any problem was found (all of them, not just one).
        """
        self.collect_signatures(program)
        self.scope = Scope()
        for stmt in program.statements:
            if isinstance(stmt, RecipeDef):
                self.check_recipe(stmt)
            else:
                self.visit(stmt)
        if self.errors:
            raise CompileErrors(self.errors)
        return self.functions

    def err(self, node, message):
        """Record an error at `node`'s position (does not stop analysis)."""
        self.errors.append(CompileError(message, node.line, node.column, self.source))

    def suggest(self, name, candidates):
        """Return ' Did you mean `x`?' if a similar name exists, else ''."""
        matches = get_close_matches(name, list(candidates), n=1, cutoff=0.6)
        return f" Did you mean `{matches[0]}`?" if matches else ""

    def visit(self, node):
        """Dispatch to visit_<ClassName>, then store the result on the node."""
        result = getattr(self, f"visit_{type(node).__name__}")(node)
        node.type = result
        return result

    def value_of(self, node):
        """Visit an expression that must produce a VALUE.

        A call to a recipe that gives nothing back is rejected here.
        """
        type_name = self.visit(node)
        if type_name == NOTHING:
            self.err(node, f"`{node.name}` doesn't give anything back, "
                           f"so it can't be used as a value.")
            node.type = ERROR
            return ERROR
        return type_name

    def check_block(self, body):
        """Check statements inside a fresh child scope (if/while bodies)."""
        self.scope = Scope(self.scope)
        for stmt in body:
            self.visit(stmt)
        self.scope = self.scope.parent

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------

    def collect_signatures(self, program):
        """Pass 1: record every top-level recipe's signature.

        Doing this before checking bodies lets recipes call each other and
        themselves (recursion) regardless of order.
        """
        for stmt in program.statements:
            if not isinstance(stmt, RecipeDef):
                continue
            if stmt.name in self.functions:
                self.err(stmt, f"A recipe called `{stmt.name}` already exists.")
                continue
            self.functions[stmt.name] = Signature(
                stmt.name,
                [p.type_name for p in stmt.params],
                stmt.return_type or NOTHING,
            )

    def check_recipe(self, node):
        """Pass 2: check one recipe body in its own isolated scope."""
        signature = self.functions.get(node.name)
        if signature is None:          # duplicate definition, already reported
            return
        saved_scope = self.scope
        self.current_recipe = signature
        self.scope = Scope()           # NO parent: recipes can't see main's variables

        for param in node.params:
            if param.name in self.scope.names:
                self.err(param, f"The parameter `{param.name}` is listed twice.")
            self.scope.declare(param.name, param.type_name)

        for stmt in node.body:
            self.visit(stmt)

        if signature.return_type != NOTHING and not always_returns(node.body):
            self.err(node, f"Recipe `{node.name}` promises to give back "
                           f"{describe_type(signature.return_type)}, but some paths "
                           f"end without a `give back`.")

        self.current_recipe = None
        self.scope = saved_scope

    def visit_RecipeDef(self, node):
        """A recipe in a nested position (top-level ones go via check_recipe)."""
        self.err(node, "Recipes can only be defined at the top of your program, "
                       "not inside another block.")

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def visit_MakeStmt(self, node):
        value_type = self.value_of(node.value)
        if self.scope.lookup(node.name) is not None:
            self.err(node, f"`{node.name}` already exists. "
                           f"Use `change {node.name} to ...` to update it.")
            return
        self.scope.declare(node.name, value_type)

    def visit_ChangeStmt(self, node):
        value_type = self.value_of(node.value)
        existing = self.scope.lookup(node.name)
        if existing is None:
            self.err(node, f"`{node.name}` hasn't been made yet, so I can't change it."
                           f"{self.suggest(node.name, self.scope.visible_names()) or f' Use `make {node.name} be ...` first.'}")
        elif ERROR not in (existing, value_type) and existing != value_type:
            self.err(node, f"`{node.name}` holds {describe_type(existing)}, "
                           f"but you're putting {describe_type(value_type)} in it.")

    def visit_SayStmt(self, node):
        self.value_of(node.value)

    def check_condition(self, node, keyword):
        """Shared by `if` and `while`: the condition must be yes/no."""
        cond_type = self.value_of(node.condition)
        if cond_type not in (YESNO, ERROR):
            self.err(node.condition,
                     f"`{keyword}` needs a yes/no condition, but this is "
                     f"{describe_type(cond_type)}. Try a comparison like "
                     f"`x is more than 0`.")

    def visit_IfStmt(self, node):
        self.check_condition(node, "if")
        self.check_block(node.then_body)
        self.check_block(node.else_body)

    def visit_WhileStmt(self, node):
        self.check_condition(node, "while")
        self.check_block(node.body)

    def visit_GiveBackStmt(self, node):
        recipe = self.current_recipe
        if recipe is None:
            self.err(node, "`give back` only works inside a recipe.")
            if node.value is not None:
                self.value_of(node.value)
            return
        if recipe.return_type == NOTHING:
            if node.value is not None:
                self.err(node, f"Recipe `{recipe.name}` doesn't say what it gives back. "
                               f"Add `gives <type>` to its first line.")
            return
        if node.value is None:
            self.err(node, f"Recipe `{recipe.name}` must give back "
                           f"{describe_type(recipe.return_type)}.")
            return
        value_type = self.value_of(node.value)
        if value_type not in (ERROR, recipe.return_type):
            self.err(node.value, f"Recipe `{recipe.name}` gives back "
                                 f"{describe_type(recipe.return_type)}, "
                                 f"but this is {describe_type(value_type)}.")

    def visit_ExprStmt(self, node):
        self.visit(node.expr)

    # ------------------------------------------------------------------
    # Expressions: each returns the expression's type
    # ------------------------------------------------------------------

    def visit_NumberLit(self, node):
        return DECIMAL if isinstance(node.value, float) else "number"

    def visit_StringLit(self, node):
        return TEXT

    def visit_BoolLit(self, node):
        return YESNO

    def visit_Variable(self, node):
        found = self.scope.lookup(node.name)
        if found is None:
            hint = self.suggest(node.name, self.scope.visible_names())
            self.err(node, f"`{node.name}` hasn't been made yet."
                           f"{hint or f' Did you forget `make {node.name} be ...`?'}")
            return ERROR
        return found

    def visit_UnaryOp(self, node):
        operand = self.value_of(node.operand)
        if operand == ERROR:
            return ERROR
        if node.op == "-":
            if operand in NUMERIC:
                return operand
            self.err(node, f"`minus` needs a number or decimal, but this is "
                           f"{describe_type(operand)}.")
            return ERROR
        if operand == YESNO:             # "not"
            return YESNO
        self.err(node, f"`not` needs a yes/no value, but this is {describe_type(operand)}.")
        return YESNO

    def visit_BinaryOp(self, node):
        left = self.value_of(node.left)
        right = self.value_of(node.right)
        op, word = node.op, OP_WORDS[node.op]
        fallback = YESNO if op not in ARITHMETIC else ERROR
        if ERROR in (left, right):
            return fallback

        if op in LOGIC:
            for side_type, side in ((left, node.left), (right, node.right)):
                if side_type != YESNO:
                    self.err(side, f"`{word}` needs yes/no values on both sides, "
                                   f"but this is {describe_type(side_type)}.")
            return YESNO

        if left != right:
            if left in NUMERIC and right in NUMERIC:
                self.err(node, f"I can't mix a number and a decimal with `{word}`. "
                               f"Use the same kind on both sides (e.g. 2.0 instead of 2).")
            else:
                self.err(node, f"I can't use `{word}` between {describe_type(left)} "
                               f"and {describe_type(right)}.")
            return fallback

        if op in ARITHMETIC:
            if left in NUMERIC:
                return left
            self.err(node, f"`{word}` only works on numbers and decimals. "
                           f"Chill can't join text yet; text can only be shown with `say`.")
            return ERROR

        if op in ORDERING:
            if left not in NUMERIC:
                self.err(node, f"`{word}` only works on numbers and decimals, "
                               f"not {describe_type(left)}.")
            return YESNO

        if left == TEXT:                  # == and !=
            self.err(node, "Chill can't compare text yet. "
                           "You can compare numbers, decimals, and yes/no values.")
        return YESNO

    def visit_Call(self, node):
        signature = self.functions.get(node.name)
        arg_types = [self.value_of(arg) for arg in node.args]
        if signature is None:
            self.err(node, f"I don't know a recipe called `{node.name}`."
                           f"{self.suggest(node.name, self.functions)}")
            return ERROR
        if len(arg_types) != len(signature.param_types):
            self.err(node, f"`{node.name}` needs {len(signature.param_types)} "
                           f"value(s) but you gave {len(arg_types)}.")
            return signature.return_type
        for arg, got, expected in zip(node.args, arg_types, signature.param_types):
            if got not in (ERROR, expected):
                self.err(arg, f"`{node.name}` expects {describe_type(expected)} here, "
                              f"but this is {describe_type(got)}.")
        return signature.return_type


def analyze(program, source=""):
    """Convenience wrapper: check a Program, return recipe signatures."""
    return Analyzer(source).check(program)
