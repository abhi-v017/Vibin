"""The driver: chains every stage and returns each stage's output.

    source -> tokens -> AST -> (type check) -> IR -> optimized IR -> LLVM IR

Both the CLI and the web API call `compile_source`, so they always agree.
"""
from dataclasses import dataclass
from typing import Any

from .analyzer import analyze
from .codegen import generate_llvm
from .ir import IRProgram
from .ir_builder import build_ir
from .lexer import tokenize
from .optimizer import optimize
from .parser import parse


@dataclass
class CompileResult:
    """Everything produced while compiling (so the UI can show every stage)."""
    tokens: list
    ast: Any
    ir: IRProgram
    optimized_ir: IRProgram      # same as `ir` when optimization is off
    llvm_ir: str                 # generated from the optimized IR


def compile_source(source, optimize_ir=True):
    """Compile Chill source text.

    Args:
        source: the program text.
        optimize_ir: run the optimizer (False = `-O0`, useful for comparison).

    Raises:
        CompileError:  lexer/parser problem (first one found).
        CompileErrors: type-checker problems (all of them).
    """
    tokens = tokenize(source)
    tree = parse(tokens, source)
    analyze(tree, source)
    ir_program = build_ir(tree)
    final_ir = optimize(ir_program) if optimize_ir else ir_program
    return CompileResult(tokens, tree, ir_program, final_ir, generate_llvm(final_ir))
