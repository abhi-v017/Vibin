"""Friendly error reporting shared by every compiler stage."""


class CompileError(Exception):
    """Raised when the user's program has a problem.

    We store WHERE the problem is (line/column) so we can point at it.
    """

    def __init__(self, message, line, column, source=""):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.source = source

    def pretty(self):
        """Build a nice multi-line message with the offending line shown."""
        lines = self.source.splitlines()
        text = lines[self.line - 1] if 0 < self.line <= len(lines) else ""
        pointer = " " * (self.column - 1) + "^"
        return (
            f"Oops! {self.message}\n"
            f"  --> line {self.line}, column {self.column}\n"
            f"   | {text}\n"
            f"   | {pointer}"
        )


class CompileErrors(Exception):
    """A bundle of several CompileError objects.

    The type checker keeps going after a mistake and collects every problem it
    finds, so the user can fix them all in one go.
    """

    def __init__(self, errors):
        super().__init__(f"{len(errors)} problems found")
        self.errors = errors

    def pretty(self):
        """Pretty-print every error, separated by a blank line."""
        return "\n\n".join(e.pretty() for e in self.errors)
