import pytest

from chill.errors import CompileError
from chill.lexer import tokenize
from chill.tokens import TokenType as T


def types(source):
    """Helper: just the token types, ignoring EOF."""
    return [t.type for t in tokenize(source)][:-1]


def test_make_statement():
    assert types("make age be 20") == [T.MAKE, T.IDENT, T.BE, T.NUMBER]


def test_number_values():
    toks = tokenize("7 3.5")
    assert toks[0].value == 7 and isinstance(toks[0].value, int)
    assert toks[1].value == 3.5


def test_multiword_operator_is_one_token():
    assert types("age is more than 18") == [T.IDENT, T.GREATER, T.NUMBER]
    assert types("a is not equal to b") == [T.IDENT, T.NOT_EQUAL, T.IDENT]
    assert types("10 divided by 2") == [T.NUMBER, T.DIVIDE, T.NUMBER]


def test_extra_spaces_inside_phrase():
    assert types("age is   more   than 18") == [T.IDENT, T.GREATER, T.NUMBER]


def test_word_that_starts_like_a_phrase_is_a_variable():
    # `island` begins with "is" but must NOT be split up
    assert types("island") == [T.IDENT]


def test_string_value():
    tok = tokenize('say "hello world"')[1]
    assert tok.type == T.STRING and tok.value == "hello world"


def test_comments_and_blank_lines_ignored():
    src = "# a comment\n\n\nsay 1\n"
    assert types(src) == [T.SAY, T.NUMBER, T.NEWLINE]


def test_line_and_column_tracking():
    toks = tokenize("say 1\nsay 2")
    second_say = toks[3]
    assert (second_say.line, second_say.column) == (2, 1)


def test_unterminated_string_error():
    with pytest.raises(CompileError) as e:
        tokenize('say "oops')
    assert "never ends" in e.value.message
    assert e.value.line == 1 and e.value.column == 5


def test_unknown_character_error():
    with pytest.raises(CompileError) as e:
        tokenize("make x be 5 @")
    assert "@" in e.value.message


def test_pretty_error_points_at_problem():
    with pytest.raises(CompileError) as e:
        tokenize("say $")
    out = e.value.pretty()
    assert "say $" in out and "^" in out
