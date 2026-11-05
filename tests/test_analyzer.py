import pytest

from chill.analyzer import analyze
from chill.errors import CompileErrors
from chill.lexer import tokenize
from chill.parser import parse


def run(source):
    """Lex + parse + analyze. Returns the annotated Program."""
    program = parse(tokenize(source), source)
    analyze(program, source)
    return program


def messages(source):
    """Return the list of error messages the analyzer produces."""
    with pytest.raises(CompileErrors) as info:
        run(source)
    return [e.message for e in info.value.errors]


def test_valid_program_passes_and_annotates_types():
    program = run("make x be 1\nsay x plus 2")
    say = program.statements[1]
    assert say.value.type == "number"
    assert say.value.left.type == "number"


def test_decimal_literal_type():
    assert run("say 1.5").statements[0].value.type == "decimal"


def test_comparison_gives_yesno():
    assert run("say 1 is more than 0").statements[0].value.type == "yesno"


def test_undefined_variable():
    assert "hasn't been made yet" in messages("say ghost")[0]


def test_did_you_mean():
    msgs = messages("make counter be 1\nsay countr")
    assert "Did you mean `counter`" in msgs[0]


def test_duplicate_make():
    assert "already exists" in messages("make x be 1\nmake x be 2")[0]


def test_change_wrong_type():
    assert "holds a number" in messages('make x be 1\nchange x to "hi"')[0]


def test_change_undefined():
    assert "hasn't been made yet" in messages("change x to 1")[0]


def test_if_needs_yesno():
    assert "yes/no condition" in messages("if 5\n say 1\ndone")[0]


def test_mixing_number_and_decimal():
    assert "mix a number and a decimal" in messages("say 1 plus 2.5")[0]


def test_text_arithmetic_rejected():
    assert "can't join text" in messages('say "a" plus "b"')[0]


def test_text_comparison_rejected():
    assert "compare text" in messages('say "a" is equal to "b"')[0]


def test_and_needs_yesno():
    assert "yes/no values" in messages("say 1 and true")[0]


def test_block_scope_ends():
    assert "hasn't been made yet" in messages("if true\n make y be 1\ndone\nsay y")[0]


def test_sibling_scopes_can_reuse_name_with_different_type():
    run('if true\n make y be 1\ndone\nif true\n make y be "t"\ndone')


def test_cannot_shadow_outer_variable():
    assert "already exists" in messages("make x be 1\nif true\n make x be 2\ndone")[0]


def test_recipe_cannot_see_main_variables():
    src = "make secret be 1\nrecipe f() gives number\n give back secret\ndone"
    assert "hasn't been made yet" in messages(src)[0]


def test_recursion_and_forward_calls_allowed():
    run("say a(1)\nrecipe a(n as number) gives number\n give back b(n)\ndone\n"
        "recipe b(n as number) gives number\n give back n\ndone")


def test_call_wrong_arity():
    src = "recipe f(a as number) gives number\n give back a\ndone\nsay f(1, 2)"
    assert "needs 1 value" in messages(src)[0]


def test_call_wrong_arg_type():
    src = 'recipe f(a as number) gives number\n give back a\ndone\nsay f("x")'
    assert "expects a number" in messages(src)[0]


def test_unknown_recipe():
    assert "don't know a recipe" in messages("say nope(1)")[0]


def test_give_back_outside_recipe():
    assert "only works inside a recipe" in messages("give back 1")[0]


def test_give_back_wrong_type():
    src = 'recipe f() gives number\n give back "x"\ndone'
    assert "gives back a number" in messages(src)[0]


def test_missing_give_back_on_some_path():
    src = "recipe f(a as number) gives number\n if a is more than 0\n  give back 1\n done\ndone"
    assert "some paths" in messages(src)[0]


def test_both_branches_returning_is_ok():
    run("recipe f(a as number) gives number\n if a is more than 0\n  give back 1\n"
        " otherwise\n  give back 2\n done\ndone")


def test_nothing_recipe_cannot_be_used_as_value():
    src = "recipe hi()\n say 1\ndone\nmake x be hi()"
    assert "doesn't give anything back" in messages(src)[0]


def test_nested_recipe_rejected():
    assert "top of your program" in messages("if true\n recipe f()\n  say 1\n done\ndone")[0]


def test_multiple_errors_collected():
    assert len(messages("say a\nsay b\nsay c")) == 3
