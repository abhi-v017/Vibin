"""Token definitions: the 'vocabulary' of the language."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    # --- values ---
    NUMBER = auto()
    STRING = auto()
    IDENT = auto()      # a variable or function name, like `age`

    # --- keywords ---
    MAKE = auto()       # make age be 20
    BE = auto()
    CHANGE = auto()     # change age to 21
    TO = auto()
    SAY = auto()        # say "hi"
    IF = auto()
    OTHERWISE = auto()
    WHILE = auto()
    DONE = auto()       # closes any block
    RECIPE = auto()     # function definition
    AS = auto()         # a as number
    GIVES = auto()      # recipe f(...) gives number
    GIVE_BACK = auto()  # return
    TRUE = auto()
    FALSE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()

    # --- operators (words!) ---
    PLUS = auto()
    MINUS = auto()
    TIMES = auto()
    DIVIDE = auto()     # "divided by"
    GREATER = auto()    # "is more than"
    LESS = auto()       # "is less than"
    GREATER_EQ = auto() # "is at least"
    LESS_EQ = auto()    # "is at most"
    EQUAL = auto()      # "is equal to"
    NOT_EQUAL = auto()  # "is not equal to"

    # --- punctuation ---
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()

    # --- structure ---
    NEWLINE = auto()    # statements end at the end of a line
    EOF = auto()        # marks "no more input"


@dataclass
class Token:
    type: TokenType
    text: str           # the exact characters from the source
    line: int
    column: int
    value: Any = None   # for NUMBER: the real int/float; STRING: its contents

    def __repr__(self):
        return f"{self.type.name}({self.text!r}) @{self.line}:{self.column}"


# One-word keywords. The lexer looks every word up in this dictionary.
KEYWORDS = {
    "make": TokenType.MAKE,
    "be": TokenType.BE,
    "change": TokenType.CHANGE,
    "to": TokenType.TO,
    "say": TokenType.SAY,
    "if": TokenType.IF,
    "otherwise": TokenType.OTHERWISE,
    "while": TokenType.WHILE,
    "done": TokenType.DONE,
    "recipe": TokenType.RECIPE,
    "as": TokenType.AS,
    "gives": TokenType.GIVES,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "plus": TokenType.PLUS,
    "minus": TokenType.MINUS,
    "times": TokenType.TIMES,
}

# Multi-word phrases that count as ONE token.
PHRASES = {
    "is more than": TokenType.GREATER,
    "is less than": TokenType.LESS,
    "is at least": TokenType.GREATER_EQ,
    "is at most": TokenType.LESS_EQ,
    "is equal to": TokenType.EQUAL,
    "is not equal to": TokenType.NOT_EQUAL,
    "divided by": TokenType.DIVIDE,
    "give back": TokenType.GIVE_BACK,
}
