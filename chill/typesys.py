"""The type system of Chill: the set of types and small helpers.

Types are plain strings so they are easy to print and compare. Four types can
hold values; NOTHING is the "type" of a call to a recipe that gives nothing
back; ERROR is a placeholder used after a mistake so one error doesn't cause a
cascade of follow-up errors.
"""

NUMBER = "number"      # 64-bit integer
DECIMAL = "decimal"    # 64-bit float
TEXT = "text"          # text (string literal)
YESNO = "yesno"        # boolean
NOTHING = "nothing"
ERROR = "error"

TYPE_NAMES = (NUMBER, DECIMAL, TEXT, YESNO)   # names a user may write
NUMERIC = (NUMBER, DECIMAL)

_FRIENDLY = {
    NUMBER: "a number",
    DECIMAL: "a decimal",
    TEXT: "text",
    YESNO: "a yes/no value",
    NOTHING: "nothing",
    ERROR: "something invalid",
}


def describe_type(type_name):
    """Return a phrase like "a number" for use inside error messages."""
    return _FRIENDLY[type_name]
