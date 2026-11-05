"""LLVM code generation: IR -> LLVM IR text, using `llvmlite`.

LLVM IR is a typed, low-level language that LLVM can turn into machine code
for any CPU. Our IR was designed to map almost 1:1:

    Chill IR                    LLVM IR (via llvmlite)
    ---------                   ----------------------
    IRFunction                  function (recipes get a `chill_` prefix;
                                <main> becomes C's `main`)
    Block                       basic block
    slot                        `alloca` in the entry block, + load/store
    BinOp / UnOp                add/sub/mul/sdiv, fadd.., icmp/fcmp, xor
    Jump / Branch / Return      br / br i1 / ret
    Print                       call to C's printf

Type mapping: number -> i64, decimal -> double, yesno -> i1, text -> i8*.
"""
from llvmlite import binding, ir

from .ir import BinOp, Branch, Call, Const, Copy, Jump, Load, Print, Return, Store, Temp, UnOp
from .typesys import DECIMAL, NOTHING, NUMBER, TEXT, YESNO

I1, I8, I32, I64 = ir.IntType(1), ir.IntType(8), ir.IntType(32), ir.IntType(64)
DOUBLE = ir.DoubleType()
LLVM_TYPES = {NUMBER: I64, DECIMAL: DOUBLE, YESNO: I1, TEXT: I8.as_pointer()}

_llvm_ready = False


def init_llvm():
    """Initialize LLVM's native target once per process."""
    global _llvm_ready
    if not _llvm_ready:
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
        _llvm_ready = True


def llvm_name(ir_name):
    """Name of a recipe in LLVM. <main> is C's `main`; user recipes are
    prefixed so they can never collide with C library functions."""
    return "main" if ir_name == "<main>" else f"chill_{ir_name}"


class CodeGen:
    """Translates an IRProgram into LLVM IR text.

    Usage:
        llvm_text = CodeGen().generate(ir_program)
    """

    def __init__(self):
        init_llvm()
        self.module = ir.Module(name="chill")
        target = binding.Target.from_default_triple()
        machine = target.create_target_machine()
        self.module.triple = binding.get_default_triple()
        self.module.data_layout = str(machine.target_data)
        self.strings = {}       # text -> constant i8* pointer (deduplicated)
        self.funcs = {}         # IR function name -> llvmlite Function
        printf_type = ir.FunctionType(I32, [I8.as_pointer()], var_arg=True)
        self.printf = ir.Function(self.module, printf_type, name="printf")
        exit_type = ir.FunctionType(ir.VoidType(), [I32])
        self.exit_fn = ir.Function(self.module, exit_type, name="exit")

    # ------------------------------------------------------------------

    def generate(self, program):
        """Generate the whole module and return it as LLVM IR text.

        Two passes so recipes can call each other in any order:
        first DECLARE every function, then DEFINE their bodies.
        """
        for func in program.functions:
            self.declare(func)
        for func in program.functions:
            self.define(func)
        return str(self.module)

    def declare(self, func):
        """Create the LLVM function signature (no body yet)."""
        if func.name == "<main>":
            fn_type = ir.FunctionType(I32, [])
        else:
            ret = ir.VoidType() if func.return_type == NOTHING else LLVM_TYPES[func.return_type]
            fn_type = ir.FunctionType(ret, [LLVM_TYPES[t] for _, t in func.params])
        self.funcs[func.name] = ir.Function(self.module, fn_type, name=llvm_name(func.name))

    def get_string(self, text):
        """Return an i8* constant pointing at a NUL-terminated copy of `text`."""
        if text not in self.strings:
            data = bytearray(text.encode("utf8") + b"\0")
            array_type = ir.ArrayType(I8, len(data))
            var = ir.GlobalVariable(self.module, array_type, name=f"str{len(self.strings)}")
            var.linkage, var.global_constant = "private", True
            var.initializer = ir.Constant(array_type, data)
            zero = ir.Constant(I32, 0)
            self.strings[text] = var.gep([zero, zero])
        return self.strings[text]

    # ------------------------------------------------------------------

    def define(self, func):
        """Emit the body of one function."""
        llfunc = self.funcs[func.name]
        blocks = {b.label: llfunc.append_basic_block(b.label) for b in func.blocks}
        builder = ir.IRBuilder()
        self.values = {name: llfunc.args[i] for i, (name, _) in enumerate(func.params)}
        self.slots = {}
        self.is_main = func.name == "<main>"

        for index, block in enumerate(func.blocks):
            builder.position_at_end(blocks[block.label])
            if index == 0:                       # all variables get stack slots up front
                for slot, type_name in func.slots.items():
                    self.slots[slot] = builder.alloca(LLVM_TYPES[type_name], name=slot)
            for instr in block.instrs:
                self.emit(builder, instr, blocks)

    def operand(self, op):
        """Turn an IR operand (Const or Temp) into an LLVM value."""
        if isinstance(op, Temp):
            return self.values[op.name]
        if op.type == TEXT:
            return self.get_string(op.value)
        if op.type == DECIMAL:
            return ir.Constant(DOUBLE, float(op.value))
        return ir.Constant(LLVM_TYPES[op.type], int(op.value))

    def emit(self, b, instr, blocks):
        """Translate ONE IR instruction using the llvmlite builder `b`."""
        if isinstance(instr, Copy):
            self.values[instr.dest.name] = self.operand(instr.src)
        elif isinstance(instr, BinOp):
            self.values[instr.dest.name] = self.binop(b, instr)
        elif isinstance(instr, UnOp):
            value = self.operand(instr.operand)
            if instr.op == "not":
                result = b.not_(value)
            elif instr.operand.type == DECIMAL:
                result = b.fmul(value, ir.Constant(DOUBLE, -1.0))
            else:
                result = b.neg(value)
            self.values[instr.dest.name] = result
        elif isinstance(instr, Load):
            self.values[instr.dest.name] = b.load(self.slots[instr.slot])
        elif isinstance(instr, Store):
            b.store(self.operand(instr.value), self.slots[instr.slot])
        elif isinstance(instr, Call):
            result = b.call(self.funcs[instr.func], [self.operand(a) for a in instr.args])
            if instr.dest is not None:
                self.values[instr.dest.name] = result
        elif isinstance(instr, Print):
            self.print_value(b, instr.value)
        elif isinstance(instr, Jump):
            b.branch(blocks[instr.target])
        elif isinstance(instr, Branch):
            b.cbranch(self.operand(instr.cond), blocks[instr.then_label],
                      blocks[instr.else_label])
        elif isinstance(instr, Return):
            if self.is_main:
                b.ret(ir.Constant(I32, 0))
            elif instr.value is None:
                b.ret_void()
            else:
                b.ret(self.operand(instr.value))
        else:
            raise NotImplementedError(type(instr).__name__)

    def binop(self, b, instr):
        """Pick the right LLVM instruction from the operator and operand type."""
        left, right = self.operand(instr.left), self.operand(instr.right)
        op, kind = instr.op, instr.left.type
        if op in (">", "<", ">=", "<=", "==", "!="):
            if kind == DECIMAL:
                return b.fcmp_ordered(op, left, right)
            if kind == YESNO:
                return b.icmp_unsigned(op, left, right)
            return b.icmp_signed(op, left, right)
        if kind == DECIMAL:
            return {"+": b.fadd, "-": b.fsub, "*": b.fmul, "/": b.fdiv}[op](left, right)
        if op == "/":
            self.guard_zero_divisor(b, right)
            return b.sdiv(left, right)
        return {"+": b.add, "-": b.sub, "*": b.mul}[op](left, right)

    def guard_zero_divisor(self, b, divisor):
        """Emit: if divisor == 0 { print an error; exit(1) }.

        Without this check, integer division by zero is UNDEFINED BEHAVIOR in
        LLVM: the optimizer may turn it into garbage instead of crashing.
        An explicit check gives every run a clear, deterministic error.
        """
        with b.if_then(b.icmp_signed("==", divisor, ir.Constant(I64, 0))):
            b.call(self.printf, [self.get_string("Runtime error: you divided by zero.\n")])
            b.call(self.exit_fn, [ir.Constant(I32, 1)])
            b.unreachable()

    def print_value(self, b, operand):
        """Print via C's printf, choosing a format string by type."""
        value = self.operand(operand)
        kind = operand.type
        if kind == YESNO:                        # show yes / no instead of 1 / 0
            value = b.select(value, self.get_string("yes"), self.get_string("no"))
            fmt = "%s\n"
        else:
            fmt = {NUMBER: "%lld\n", DECIMAL: "%g\n", TEXT: "%s\n"}[kind]
        b.call(self.printf, [self.get_string(fmt), value])


def generate_llvm(program):
    """Convenience wrapper: IRProgram in, LLVM IR text out."""
    return CodeGen().generate(program)
