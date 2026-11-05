"""The lexer: turns raw text into a list of tokens."""
import re

from .errors import CompileError
from .tokens import KEYWORDS, PHRASES, Token, TokenType

SINGLE_CHARS = {
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    ",": TokenType.COMMA,
}


def _build_phrase_patterns():
    """Turn "is more than" into a regex that allows any spacing between words.

    Longest phrases go first so "is not equal to" is tried before shorter ones.
    """
    patterns = []
    for phrase, token_type in sorted(PHRASES.items(), key=lambda p: -len(p[0])):
        words = phrase.split()
        regex = r"[ \t]+".join(re.escape(w) for w in words) + r"\b"
        patterns.append((re.compile(regex, re.IGNORECASE), token_type))
    return patterns


PHRASE_PATTERNS = _build_phrase_patterns()


class Lexer:
    def __init__(self, source):
        self.source = source
        self.pos = 0        # index of the character we're looking at
        self.line = 1       # human-friendly position, for error messages
        self.column = 1
        self.tokens = []

    # ---------- small helpers (the "cursor" over the text) ----------

    def at_end(self):
        return self.pos >= len(self.source)

    def peek(self, offset=0):
        """Look at a character WITHOUT moving forward."""
        i = self.pos + offset
        return self.source[i] if i < len(self.source) else ""

    def advance(self):
        """Return the current character and move forward by one."""
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def error(self, message, line=None, column=None):
        return CompileError(message, line or self.line, column or self.column, self.source)

    def add(self, token_type, text, line, column, value=None):
        self.tokens.append(Token(token_type, text, line, column, value))

    # ---------- the main loop ----------

    def tokenize(self):
        while not self.at_end():
            ch = self.peek()

            if ch in " \t\r":
                self.advance()                      # skip spaces
            elif ch == "\n":
                self.read_newline()
            elif ch == "#":
                self.skip_comment()
            elif ch == '"':
                self.read_string()
            elif ch.isdigit():
                self.read_number()
            elif ch.isalpha() or ch == "_":
                self.read_word()
            elif ch in SINGLE_CHARS:
                line, col = self.line, self.column
                self.advance()
                self.add(SINGLE_CHARS[ch], ch, line, col)
            else:
                raise self.error(f"I don't know what `{ch}` means here.")

        self.add(TokenType.EOF, "", self.line, self.column)
        return self.tokens

    # ---------- one method per kind of token ----------

    def read_newline(self):
        line, col = self.line, self.column
        self.advance()
        # Collapse blank lines: only add NEWLINE if the last token isn't one.
        if self.tokens and self.tokens[-1].type != TokenType.NEWLINE:
            self.add(TokenType.NEWLINE, "\\n", line, col)

    def skip_comment(self):
        while not self.at_end() and self.peek() != "\n":
            self.advance()

    def read_number(self):
        line, col = self.line, self.column
        start = self.pos
        while self.peek().isdigit():
            self.advance()
        # A decimal point only counts if a digit follows (so `5.` is not a decimal)
        if self.peek() == "." and self.peek(1).isdigit():
            self.advance()
            while self.peek().isdigit():
                self.advance()
        text = self.source[start:self.pos]
        value = float(text) if "." in text else int(text)
        self.add(TokenType.NUMBER, text, line, col, value)

    def read_string(self):
        line, col = self.line, self.column
        self.advance()                              # skip opening quote
        start = self.pos
        while not self.at_end() and self.peek() not in '"\n':
            self.advance()
        if self.at_end() or self.peek() == "\n":
            raise self.error(
                'This text never ends. Did you forget the closing " ?', line, col
            )
        contents = self.source[start:self.pos]
        self.advance()                              # skip closing quote
        self.add(TokenType.STRING, f'"{contents}"', line, col, contents)

    def read_word(self):
        line, col = self.line, self.column

        # 1) Try multi-word phrases first ("is more than", "divided by", ...)
        for pattern, token_type in PHRASE_PATTERNS:
            match = pattern.match(self.source, self.pos)
            if match:
                text = match.group()
                for _ in text:                      # move the cursor past it
                    self.advance()
                self.add(token_type, text, line, col)
                return

        # 2) Otherwise read one whole word
        start = self.pos
        while self.peek().isalnum() or self.peek() == "_":
            self.advance()
        text = self.source[start:self.pos]

        # 3) Keyword or variable name? Dictionary lookup decides.
        token_type = KEYWORDS.get(text.lower(), TokenType.IDENT)
        self.add(token_type, text, line, col)


def tokenize(source):
    return Lexer(source).tokenize()
