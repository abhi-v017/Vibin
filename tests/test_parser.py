import pytest

from chill.ast_nodes import (
    BinaryOp, BoolLit, Call, ChangeStmt, ExprStmt, GiveBackStmt, IfStmt,
    MakeStmt, NumberLit, RecipeDef, SayStmt, UnaryOp, Variable, WhileStmt,
)
from chill.errors import CompileError
from chill.lexer import tokenize
from chill.parser import parse


def ast(source):
    """Helper: source text -> Program node."""
    return parse(tokenize(source), source)


def first(source):
    """Helper: the first statement of a program."""
    return ast(source).statements[0]


def expr(source):
    """Helper: parse `say <source>` and return just the expression."""
    return first(f"say {source}").value


# ---------- statements ----------

def test_make():
    node = first("make age be 20")
    assert isinstance(node, MakeStmt) and node.name == "age"
    assert node.value == NumberLit(20, line=1, column=13)


def test_change_and_say():
    prog = ast("change x to 5\nsay x")
    assert isinstance(prog.statements[0], ChangeStmt)
    assert isinstance(prog.statements[1], SayStmt)


def test_if_otherwise():
    node = first("if x is more than 1\n say 1\notherwise\n say 2\ndone")
    assert isinstance(node, IfStmt)
    assert len(node.then_body) == 1 and len(node.else_body) == 1


def test_if_without_otherwise():
    node = first("if true\n say 1\ndone")
    assert node.else_body == []


def test_while():
    node = first("while i is less than 3\n change i to i plus 1\ndone")
    assert isinstance(node, WhileStmt) and len(node.body) == 1


def test_recipe_and_give_back():
    node = first("recipe add(a as number, b as decimal) gives number\n give back a plus b\ndone")
    assert isinstance(node, RecipeDef)
    assert [(p.name, p.type_name) for p in node.params] == [("a", "number"), ("b", "decimal")]
    assert node.return_type == "number"
    assert isinstance(node.body[0], GiveBackStmt)


def test_recipe_without_return_type():
    assert first("recipe hi()\n say 1\ndone").return_type is None


def test_param_needs_type():
    assert "what type" in err("recipe f(x)\n say 1\ndone").message


def test_unknown_type_name():
    assert "expected a type" in err("recipe f(x as banana)\n say 1\ndone").message


def test_call_statement():
    node = first("greet()")
    assert isinstance(node, ExprStmt) and isinstance(node.expr, Call)


def test_nested_blocks():
    src = "while true\n if true\n  say 1\n done\ndone"
    outer = first(src)
    assert isinstance(outer.body[0], IfStmt)


# ---------- expressions: precedence & associativity ----------

def test_times_binds_tighter_than_plus():
    e = expr("1 plus 2 times 3")
    assert e.op == "+" and e.right.op == "*"


def test_parentheses_override_precedence():
    e = expr("(1 plus 2) times 3")
    assert e.op == "*" and e.left.op == "+"


def test_left_associativity():
    e = expr("10 minus 3 minus 2")        # must be (10 - 3) - 2
    assert e.op == "-" and e.left.op == "-" and e.right.value == 2


def test_comparison_lower_than_arithmetic():
    e = expr("a plus 1 is more than b")
    assert e.op == ">" and e.left.op == "+"


def test_and_or_not_precedence():
    e = expr("a or b and not c")          # a or (b and (not c))
    assert e.op == "or" and e.right.op == "and"
    assert isinstance(e.right.right, UnaryOp) and e.right.right.op == "not"


def test_unary_minus():
    e = expr("minus 5")
    assert isinstance(e, UnaryOp) and e.op == "-"


def test_call_with_args():
    e = expr("add(1, x plus 2)")
    assert isinstance(e, Call) and len(e.args) == 2


def test_bool_literal():
    assert expr("true") == BoolLit(True, line=1, column=5)


def test_positions_recorded():
    node = first("\nmake x be 1")
    assert (node.line, node.column) == (2, 1)


# ---------- friendly errors ----------

def err(source):
    with pytest.raises(CompileError) as info:
        ast(source)
    return info.value


def test_missing_be():
    e = err("make age 20")
    assert "`be`" in e.message and e.line == 1


def test_missing_done():
    e = err("if true\n say 1\n")
    assert "never gets closed" in e.message and e.line == 1


def test_stray_done():
    assert "doesn't match" in err("done").message


def test_missing_value():
    assert "expected a value" in err("make x be").message


def test_extra_tokens_on_line():
    assert "line to end" in err("say 1 2").message


def test_bare_name_is_not_a_statement():
    assert "doesn't do anything" in err("age").message


def test_unclosed_paren():
    assert "`)`" in err("say (1 plus 2").message


def test_bad_line_start():
    assert "start a line" in err("5 plus 5").message
