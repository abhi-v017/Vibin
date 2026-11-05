from chill.analyzer import analyze
from chill.ir import BinOp, Branch, Load, Print, Store, format_ir
from chill.ir_builder import build_ir
from chill.lexer import tokenize
from chill.optimizer import optimize
from chill.parser import parse


def lower(source):
    """Source -> (unoptimized IR, optimized IR)."""
    tree = parse(tokenize(source), source)
    analyze(tree, source)
    ir = build_ir(tree)
    return ir, optimize(ir)


def instrs(program, func=0):
    return [i for b in program.functions[func].blocks for i in b.instrs]


def test_constant_folding():
    _, opt = lower("say 2 plus 3 times 4")
    assert not any(isinstance(i, BinOp) for i in instrs(opt))
    assert str([i for i in instrs(opt) if isinstance(i, Print)][0]) == "print 14"


def test_store_forwarding_and_propagation():
    _, opt = lower("make x be 5\nsay x plus 1")
    assert "print 6" in format_ir(opt)
    assert not any(isinstance(i, (Load, Store)) for i in instrs(opt))


def test_branch_folding_removes_dead_branch():
    _, opt = lower('if true\n say "a"\notherwise\n say "b"\ndone')
    text = format_ir(opt)
    assert '"a"' in text and '"b"' not in text
    assert not any(isinstance(i, Branch) for i in instrs(opt))


def test_dead_code_elimination():
    _, opt = lower("make unused be 1 plus 2\nsay 1")
    assert "unused" not in format_ir(opt)


def test_division_by_zero_not_folded():
    _, opt = lower("say 1 divided by 0")
    assert any(isinstance(i, BinOp) and i.op == "/" for i in instrs(opt))


def test_integer_division_truncates_toward_zero():
    _, opt = lower("say minus 7 divided by 2")
    assert "print -3" in format_ir(opt)


def test_loop_variable_is_not_folded_away():
    _, opt = lower("make i be 0\nwhile i is less than 3\n change i to i plus 1\ndone\nsay i")
    assert any(isinstance(i, BinOp) for i in instrs(opt))   # the loop must remain


def test_original_ir_untouched_by_optimize():
    before, after = lower("say 1 plus 1")
    assert any(isinstance(i, BinOp) for i in instrs(before))
    assert format_ir(before) != format_ir(after)


def test_short_circuit_blocks_exist_unoptimized():
    before, _ = lower("say true and false")
    assert any(b.label.startswith("rhs") for b in before.functions[0].blocks)
