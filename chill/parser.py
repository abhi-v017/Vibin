"""The parser: turns a flat list of tokens into an AST.

Technique: RECURSIVE DESCENT. There is one method per grammar rule, and rules
call each other. The call structure of the methods mirrors the grammar.

Grammar of Chill (EBNF; NEWLINE/EOF are tokens from the lexer)
--------------------------------------------------------------
program     = { statement } EOF
statement   = make | change | say | if | while | recipe | giveback | callstmt
make        = "make" IDENT "be" expr NEWLINE
change      = "change" IDENT "to" expr NEWLINE
say         = "say" expr NEWLINE
if          = "if" expr NEWLINE block [ "otherwise" NEWLINE block ] "done" NEWLINE
while       = "while" expr NEWLINE block "done" NEWLINE
recipe      = "recipe" IDENT "(" [ param { "," param } ] ")" [ "gives" type ]
              NEWLINE block "done"
param       = IDENT "as" type
type        = "number" | "decimal" | "text" | "yesno"
giveback    = "give back" [ expr ] NEWLINE
callstmt    = call NEWLINE
block       = { statement }

Expression precedence, weakest (evaluated last) to strongest (first):
    or  <  and  <  not  <  comparisons  <  plus/minus  <  times/divided by
        <  unary minus  <  call  <  literals, variables, ( expr )

Weaker rules call stronger rules first; that is what makes `1 plus 2 times 3`
group as `1 plus (2 times 3)`.
"""
from .ast_nodes import (
    BinaryOp, BoolLit, Call, ChangeStmt, ExprStmt, GiveBackStmt, IfStmt,
    MakeStmt, NumberLit, Param, Program, RecipeDef, SayStmt, StringLit, UnaryOp,
    Variable, WhileStmt,
)
from .errors import CompileError
from .tokens import TokenType as T
from .typesys import TYPE_NAMES

# Maps operator tokens to the symbol stored in BinaryOp.op
OR_OPS = {T.OR: "or"}
AND_OPS = {T.AND: "and"}
COMPARE_OPS = {
    T.GREATER: ">", T.LESS: "<", T.GREATER_EQ: ">=",
    T.LESS_EQ: "<=", T.EQUAL: "==", T.NOT_EQUAL: "!=",
}
TERM_OPS = {T.PLUS: "+", T.MINUS: "-"}
FACTOR_OPS = {T.TIMES: "*", T.DIVIDE: "/"}


def describe(token):
    """Return a human-friendly name for a token, for use in error messages.

    Example: a NEWLINE token becomes "the end of the line" instead of "\\n".
    """
    if token.type == T.NEWLINE:
        return "the end of the line"
    if token.type == T.EOF:
        return "the end of the file"
    return f"`{token.text}`"


class Parser:
    """Builds an AST from tokens.

    Usage:
        ast = Parser(tokens, source).parse()

    Attributes:
        tokens:  the token list produced by the lexer (ends with EOF).
        source:  original program text, only used to show the line in errors.
        current: index of the token we are looking at (the "cursor").
    """

    def __init__(self, tokens, source=""):
        self.tokens = tokens
        self.source = source
        self.current = 0

    # ==================================================================
    # Cursor helpers: the small toolkit every parse method uses
    # ==================================================================

    def peek(self):
        """Return the current token without consuming it."""
        return self.tokens[self.current]

    def check(self, *types):
        """Return True if the current token's type is one of `types`."""
        return self.peek().type in types

    def advance(self):
        """Consume and return the current token. Never moves past EOF."""
        token = self.tokens[self.current]
        if token.type != T.EOF:
            self.current += 1
        return token

    def match(self, *types):
        """Consume the current token only if it is one of `types`.

        Returns:
            The consumed token, or None if it didn't match.
        """
        if self.check(*types):
            return self.advance()
        return None

    def expect(self, token_type, message):
        """Consume a token of `token_type` or raise a friendly error.

        Args:
            token_type: the TokenType we require next.
            message: what to tell the user if it's missing.
        """
        if self.check(token_type):
            return self.advance()
        raise self.error(f"{message} (found {describe(self.peek())} instead)")

    def error(self, message, token=None):
        """Build a CompileError located at `token` (default: current token)."""
        token = token or self.peek()
        return CompileError(message, token.line, token.column, self.source)

    def skip_newlines(self):
        """Consume any NEWLINE tokens (blank space between statements)."""
        while self.match(T.NEWLINE):
            pass

    def end_statement(self):
        """Require that a statement ends at a line break (or end of file)."""
        if self.match(T.NEWLINE) or self.check(T.EOF):
            return
        raise self.error(
            f"I expected the line to end here, but found {describe(self.peek())}."
        )

    # ==================================================================
    # Statements
    # ==================================================================

    def parse(self):
        """Entry point. Parse the whole token list into a Program node."""
        statements = []
        self.skip_newlines()
        while not self.check(T.EOF):
            statements.append(self.parse_statement())
            self.skip_newlines()
        return Program(statements, line=1, column=1)

    def parse_statement(self):
        """Parse ONE statement by looking at its first token and dispatching.

        This is the "switchboard" of the parser: the first token tells us
        which rule to use, with no backtracking needed.
        """
        token = self.peek()
        handlers = {
            T.MAKE: self.parse_make,
            T.CHANGE: self.parse_change,
            T.SAY: self.parse_say,
            T.IF: self.parse_if,
            T.WHILE: self.parse_while,
            T.RECIPE: self.parse_recipe,
            T.GIVE_BACK: self.parse_give_back,
            T.IDENT: self.parse_call_statement,
        }
        handler = handlers.get(token.type)
        if handler is None:
            if token.type in (T.DONE, T.OTHERWISE):
                raise self.error(
                    f"`{token.text}` doesn't match anything. It must close or "
                    f"continue an `if`, `while`, or `recipe`."
                )
            raise self.error(
                f"I don't know how to start a line with {describe(token)}. "
                f"Lines start with make, change, say, if, while, recipe, or give back."
            )
        statement = handler()
        self.end_statement()
        return statement

    def parse_block(self, opener, *stoppers):
        """Parse statements until one of the `stoppers` tokens appears.

        Used for the bodies of if / while / recipe. The stopper token (e.g.
        `done`) is NOT consumed here; the caller does that.

        Args:
            opener: the token that started the block (for the error message).
            stoppers: token types that end this block.

        Raises:
            CompileError: if the file ends before a stopper is found.
        """
        body = []
        self.skip_newlines()
        while not self.check(*stoppers):
            if self.check(T.EOF):
                raise self.error(
                    f"This `{opener.text}` never gets closed. "
                    f"Add `done` at the end of it.",
                    opener,
                )
            body.append(self.parse_statement())
            self.skip_newlines()
        return body

    def parse_make(self):
        """make <name> be <expr>"""
        tok = self.advance()
        name = self.expect(
            T.IDENT, "After `make` I expected a variable name, like: make age be 20"
        )
        self.expect(
            T.BE, f"After `make {name.text}` I expected `be`, like: make {name.text} be 20"
        )
        value = self.parse_expression()
        return MakeStmt(name.text, value, line=tok.line, column=tok.column)

    def parse_change(self):
        """change <name> to <expr>"""
        tok = self.advance()
        name = self.expect(T.IDENT, "After `change` I expected a variable name.")
        self.expect(
            T.TO, f"After `change {name.text}` I expected `to`, like: change {name.text} to 5"
        )
        value = self.parse_expression()
        return ChangeStmt(name.text, value, line=tok.line, column=tok.column)

    def parse_say(self):
        """say <expr>"""
        tok = self.advance()
        value = self.parse_expression()
        return SayStmt(value, line=tok.line, column=tok.column)

    def parse_if(self):
        """if <cond> NEWLINE block [otherwise NEWLINE block] done"""
        tok = self.advance()
        condition = self.parse_expression()
        self.expect(T.NEWLINE, "The body of an `if` must start on the next line.")
        then_body = self.parse_block(tok, T.DONE, T.OTHERWISE)

        else_body = []
        if self.match(T.OTHERWISE):
            self.expect(T.NEWLINE, "The body after `otherwise` must start on the next line.")
            else_body = self.parse_block(tok, T.DONE)

        self.expect(T.DONE, "I expected `done` to close the `if`.")
        return IfStmt(condition, then_body, else_body, line=tok.line, column=tok.column)

    def parse_while(self):
        """while <cond> NEWLINE block done"""
        tok = self.advance()
        condition = self.parse_expression()
        self.expect(T.NEWLINE, "The body of a `while` must start on the next line.")
        body = self.parse_block(tok, T.DONE)
        self.expect(T.DONE, "I expected `done` to close the `while`.")
        return WhileStmt(condition, body, line=tok.line, column=tok.column)

    def parse_type(self):
        """Parse a type name (number, decimal, text, yesno) and return it.

        Type names are ordinary identifiers to the lexer; only here, where a
        type is expected, do we give them that meaning. So `number` is still
        usable as a variable name elsewhere.
        """
        token = self.peek()
        if token.type == T.IDENT and token.text.lower() in TYPE_NAMES:
            self.advance()
            return token.text.lower()
        raise self.error(
            f"I expected a type here: number, decimal, text, or yesno "
            f"(found {describe(token)})."
        )

    def parse_recipe(self):
        """recipe <name>(<p> as <type>, ...) [gives <type>] NEWLINE block done"""
        tok = self.advance()
        name = self.expect(
            T.IDENT, "A recipe needs a name, like: recipe double(x as number) gives number"
        )
        self.expect(
            T.LPAREN,
            f"After the recipe name I expected `(`, like: recipe {name.text}(x as number)",
        )
        params = []
        if not self.check(T.RPAREN):
            while True:
                p = self.expect(T.IDENT, "I expected a parameter name here.")
                self.expect(
                    T.AS,
                    f"Tell me what type `{p.text}` is, like: {p.text} as number",
                )
                type_name = self.parse_type()
                params.append(Param(p.text, type_name, line=p.line, column=p.column))
                if not self.match(T.COMMA):
                    break
        self.expect(T.RPAREN, "I expected `)` to close the parameter list.")
        return_type = None
        if self.match(T.GIVES):
            return_type = self.parse_type()
        self.expect(T.NEWLINE, "The body of a recipe must start on the next line.")
        body = self.parse_block(tok, T.DONE)
        self.expect(T.DONE, "I expected `done` to close the recipe.")
        return RecipeDef(
            name.text, params, return_type, body, line=tok.line, column=tok.column
        )

    def parse_give_back(self):
        """give back [<expr>]  (the value is optional)"""
        tok = self.advance()
        value = None
        if not self.check(T.NEWLINE, T.EOF):
            value = self.parse_expression()
        return GiveBackStmt(value, line=tok.line, column=tok.column)

    def parse_call_statement(self):
        """A line that starts with a name must be a recipe call, e.g. greet()."""
        start = self.peek()
        expr = self.parse_expression()
        if not isinstance(expr, Call):
            raise self.error(
                f"`{start.text}` on its own doesn't do anything. "
                f"Did you mean `make {start.text} be ...` or `say {start.text}`?",
                start,
            )
        return ExprStmt(expr, line=start.line, column=start.column)

    # ==================================================================
    # Expressions (one method per precedence level)
    # ==================================================================

    def parse_expression(self):
        """Parse any expression. Starts at the weakest level (`or`)."""
        return self.parse_or()

    def _parse_binary_level(self, parse_operand, operators):
        """Shared logic for all left-associative binary levels.

        Parses `operand (op operand)*` and folds it LEFT to right, so
        `10 minus 3 minus 2` becomes `(10 minus 3) minus 2`.

        Args:
            parse_operand: the next-stronger rule's method.
            operators: dict mapping TokenType -> operator symbol for this level.
        """
        left = parse_operand()
        while self.peek().type in operators:
            op_token = self.advance()
            right = parse_operand()
            left = BinaryOp(
                operators[op_token.type], left, right,
                line=op_token.line, column=op_token.column,
            )
        return left

    def parse_or(self):
        """Weakest level: a or b"""
        return self._parse_binary_level(self.parse_and, OR_OPS)

    def parse_and(self):
        """a and b"""
        return self._parse_binary_level(self.parse_not, AND_OPS)

    def parse_not(self):
        """not a  (right-recursive so `not not a` works)"""
        if self.check(T.NOT):
            tok = self.advance()
            operand = self.parse_not()
            return UnaryOp("not", operand, line=tok.line, column=tok.column)
        return self.parse_comparison()

    def parse_comparison(self):
        """a is more than b, a is equal to b, ..."""
        return self._parse_binary_level(self.parse_term, COMPARE_OPS)

    def parse_term(self):
        """a plus b, a minus b"""
        return self._parse_binary_level(self.parse_factor, TERM_OPS)

    def parse_factor(self):
        """a times b, a divided by b (binds tighter than plus/minus)"""
        return self._parse_binary_level(self.parse_unary, FACTOR_OPS)

    def parse_unary(self):
        """Negation: minus a"""
        if self.check(T.MINUS):
            tok = self.advance()
            operand = self.parse_unary()
            return UnaryOp("-", operand, line=tok.line, column=tok.column)
        return self.parse_call()

    def parse_call(self):
        """A primary, optionally followed by (args) if it's a name."""
        expr = self.parse_primary()
        if isinstance(expr, Variable) and self.check(T.LPAREN):
            self.advance()  # consume "("
            args = []
            if not self.check(T.RPAREN):
                while True:
                    args.append(self.parse_expression())
                    if not self.match(T.COMMA):
                        break
            self.expect(T.RPAREN, f"I expected `)` to close the call to {expr.name}.")
            return Call(expr.name, args, line=expr.line, column=expr.column)
        return expr

    def parse_primary(self):
        """Strongest level: the basic building blocks of an expression.

        A number, text, true/false, a variable name, or an expression in
        parentheses (which lets users override precedence).
        """
        token = self.peek()
        pos = {"line": token.line, "column": token.column}

        if self.match(T.NUMBER):
            return NumberLit(token.value, **pos)
        if self.match(T.STRING):
            return StringLit(token.value, **pos)
        if self.match(T.TRUE):
            return BoolLit(True, **pos)
        if self.match(T.FALSE):
            return BoolLit(False, **pos)
        if self.match(T.IDENT):
            return Variable(token.text, **pos)
        if self.match(T.LPAREN):
            inner = self.parse_expression()
            self.expect(T.RPAREN, "I expected `)` to close the parenthesis.")
            return inner

        raise self.error(
            f"I expected a value here (a number, text, or variable) "
            f"but found {describe(token)}."
        )


def parse(tokens, source=""):
    """Convenience wrapper: tokens in, AST (Program node) out."""
    return Parser(tokens, source).parse()
