"""IR builder: lowers the typed AST into IR (three-address code).

Think of it as a second tree walk (like the analyzer) that, instead of
checking, EMITS instructions. Each `stmt_*` method emits instructions;
each `expr_*` method emits instructions and returns the OPERAND (a Const
or Temp) holding the expression's result.

Control flow becomes basic blocks joined by Jump/Branch:

    if c: A otherwise: B      while c: body
      branch c ? then : else    cond:  branch c ? body : end
      then: A; jump end         body:  ...; jump cond
      else: B; jump end         end:
      end:

`and` / `or` SHORT-CIRCUIT: the right side only runs when needed, using a
hidden slot plus branches (the right side lives in its own block).
"""
from .ast_nodes import RecipeDef
from .ir import (
    BinOp, Block, Branch, Call, Const, IRFunction, IRProgram, Jump, Load,
    Print, Return, Store, Temp, UnOp,
)
from .typesys import DECIMAL, NOTHING, NUMBER, TEXT, YESNO

MAIN = "<main>"


def default_const(type_name):
    """A zero-ish constant of a type (used for unreachable fall-through returns)."""
    return Const({NUMBER: 0, DECIMAL: 0.0, TEXT: "", YESNO: False}[type_name], type_name)


class IRBuilder:
    """Builds an IRProgram from a type-annotated Program node.

    Usage:
        ir = IRBuilder().build(program)
    """

    def build(self, program):
        """Lower the whole program: top-level code -> <main>, each recipe -> a function."""
        recipes = [s for s in program.statements if isinstance(s, RecipeDef)]
        top_level = [s for s in program.statements if not isinstance(s, RecipeDef)]

        functions = [self.build_function(MAIN, [], NOTHING, top_level)]
        for recipe in recipes:
            params = [(p.name, p.type_name) for p in recipe.params]
            functions.append(
                self.build_function(recipe.name, params, recipe.return_type or NOTHING,
                                    recipe.body))
        return IRProgram(functions)

    # ------------------------------------------------------------------
    # Per-function state and helpers
    # ------------------------------------------------------------------

    def build_function(self, name, params, return_type, body):
        """Create an IRFunction and fill it from `body`."""
        self.func = IRFunction(name, [(f"p.{n}", t) for n, t in params], return_type)
        self.temp_n = self.label_n = self.slot_n = 0
        self.scopes = [{}]                       # source name -> unique slot name
        self.block = self.new_block("entry")

        for pname, ptype in params:              # copy arguments into slots
            slot = self.declare(pname, ptype)
            self.emit(Store(slot, Temp(f"p.{pname}", ptype)))

        for stmt in body:
            self.stmt(stmt)

        if not self.block.terminated():          # fell off the end of the function
            self.emit(Return(None if return_type == NOTHING else default_const(return_type)))
        return self.func

    def new_block(self, hint):
        """Create a block with a unique label and register it on the function."""
        label = hint if hint == "entry" else f"{hint}.{self.label_n}"
        self.label_n += 1
        block = Block(label)
        self.func.blocks.append(block)
        return block

    def new_temp(self, type_name):
        """Make a fresh temporary (t1, t2, ...)."""
        self.temp_n += 1
        return Temp(f"t{self.temp_n}", type_name)

    def declare(self, name, type_name):
        """Create a uniquely named slot for a source variable in the current scope.

        Unique names (x.0, x.1, ...) let sibling scopes reuse a name safely.
        """
        slot = f"{name}.{self.slot_n}"
        self.slot_n += 1
        self.func.slots[slot] = type_name
        self.scopes[-1][name] = slot
        return slot

    def hidden_slot(self, type_name):
        """A slot not tied to any source variable (used by and/or)."""
        slot = f"_sc.{self.slot_n}"
        self.slot_n += 1
        self.func.slots[slot] = type_name
        return slot

    def lookup(self, name):
        """Find the slot for a source variable, innermost scope first."""
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise KeyError(name)   # the analyzer guarantees this never happens

    def emit(self, instr):
        """Append an instruction. If the current block is already terminated
        (code after `give back`), start a fresh unreachable block first."""
        if self.block.terminated():
            self.block = self.new_block("dead")
        self.block.instrs.append(instr)

    def scoped(self, body):
        """Build a nested block of statements in a new variable scope."""
        self.scopes.append({})
        for stmt in body:
            self.stmt(stmt)
        self.scopes.pop()

    def stmt(self, node):
        getattr(self, f"stmt_{type(node).__name__}")(node)

    def expr(self, node):
        return getattr(self, f"expr_{type(node).__name__}")(node)

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def stmt_MakeStmt(self, node):
        value = self.expr(node.value)            # evaluate BEFORE declaring
        self.emit(Store(self.declare(node.name, node.value.type), value))

    def stmt_ChangeStmt(self, node):
        self.emit(Store(self.lookup(node.name), self.expr(node.value)))

    def stmt_SayStmt(self, node):
        self.emit(Print(self.expr(node.value)))

    def stmt_ExprStmt(self, node):
        self.expr(node.expr)

    def stmt_GiveBackStmt(self, node):
        self.emit(Return(None if node.value is None else self.expr(node.value)))

    def stmt_IfStmt(self, node):
        cond = self.expr(node.condition)
        then_b = self.new_block("then")
        else_b = self.new_block("else") if node.else_body else None
        end_b = self.new_block("end")
        self.emit(Branch(cond, then_b.label, (else_b or end_b).label))

        self.block = then_b
        self.scoped(node.then_body)
        self.emit(Jump(end_b.label))

        if else_b:
            self.block = else_b
            self.scoped(node.else_body)
            self.emit(Jump(end_b.label))
        self.block = end_b

    def stmt_WhileStmt(self, node):
        cond_b = self.new_block("cond")
        body_b = self.new_block("body")
        end_b = self.new_block("end")
        self.emit(Jump(cond_b.label))

        self.block = cond_b
        cond = self.expr(node.condition)
        self.emit(Branch(cond, body_b.label, end_b.label))

        self.block = body_b
        self.scoped(node.body)
        self.emit(Jump(cond_b.label))
        self.block = end_b

    # ------------------------------------------------------------------
    # Expressions (each returns an operand)
    # ------------------------------------------------------------------

    def expr_NumberLit(self, node):
        return Const(node.value, node.type)

    def expr_StringLit(self, node):
        return Const(node.value, node.type)

    def expr_BoolLit(self, node):
        return Const(node.value, node.type)

    def expr_Variable(self, node):
        temp = self.new_temp(node.type)
        self.emit(Load(temp, self.lookup(node.name)))
        return temp

    def expr_UnaryOp(self, node):
        operand = self.expr(node.operand)
        temp = self.new_temp(node.type)
        self.emit(UnOp(temp, node.op, operand))
        return temp

    def expr_BinaryOp(self, node):
        if node.op in ("and", "or"):
            return self.short_circuit(node)
        left = self.expr(node.left)
        right = self.expr(node.right)
        temp = self.new_temp(node.type)
        self.emit(BinOp(temp, node.op, left, right))
        return temp

    def short_circuit(self, node):
        """Lower `a and b` / `a or b` so `b` is evaluated only when needed.

            slot = a
            and: branch a ? rhs : end      or: branch a ? end : rhs
            rhs: slot = b; jump end
            end: result = slot
        """
        slot = self.hidden_slot(YESNO)
        left = self.expr(node.left)
        self.emit(Store(slot, left))
        rhs_b = self.new_block("rhs")
        end_b = self.new_block("end")
        if node.op == "and":
            self.emit(Branch(left, rhs_b.label, end_b.label))
        else:
            self.emit(Branch(left, end_b.label, rhs_b.label))

        self.block = rhs_b
        self.emit(Store(slot, self.expr(node.right)))
        self.emit(Jump(end_b.label))

        self.block = end_b
        result = self.new_temp(YESNO)
        self.emit(Load(result, slot))
        return result

    def expr_Call(self, node):
        args = [self.expr(a) for a in node.args]
        dest = None if node.type == NOTHING else self.new_temp(node.type)
        self.emit(Call(dest, node.name, args))
        return dest


def build_ir(program):
    """Convenience wrapper: typed AST in, IRProgram out."""
    return IRBuilder().build(program)
