"""Command-line entry point.

    python -m chill prog.chill --run            # compile and run (JIT)
    python -m chill prog.chill -o prog          # build a native executable
    python -m chill prog.chill --tokens --ast   # inspect compiler stages
    python -m chill prog.chill --ir --opt-ir    # IR before / after optimizing
    python -m chill prog.chill --llvm           # generated LLVM IR
    python -m chill prog.chill -O0 --run        # skip the optimizer
"""
import argparse
import sys

from .ast_nodes import dump
from .compiler import compile_source
from .errors import CompileError, CompileErrors
from .ir import format_ir


def build_parser():
    """Define the command-line options."""
    cli = argparse.ArgumentParser(prog="chill", description="The Chill compiler")
    cli.add_argument("file", help="path to a .chill source file")
    cli.add_argument("--tokens", action="store_true", help="print the token list")
    cli.add_argument("--ast", action="store_true", help="print the syntax tree")
    cli.add_argument("--ir", action="store_true", help="print the IR")
    cli.add_argument("--opt-ir", action="store_true", help="print the optimized IR")
    cli.add_argument("--llvm", action="store_true", help="print the LLVM IR")
    cli.add_argument("--run", action="store_true", help="run the program (JIT)")
    cli.add_argument("-o", metavar="OUT", help="build a native executable")
    cli.add_argument("-O0", dest="no_opt", action="store_true", help="disable optimizer")
    return cli


def main():
    """Compile the file and perform every action the flags ask for."""
    args = build_parser().parse_args()
    with open(args.file) as handle:
        source = handle.read()

    try:
        result = compile_source(source, optimize_ir=not args.no_opt)
    except (CompileError, CompileErrors) as error:
        print(error.pretty())
        return 1

    if args.tokens:
        print("\n".join(map(str, result.tokens)))
    if args.ast:
        print(dump(result.ast))
    if args.ir:
        print(format_ir(result.ir))
    if args.opt_ir:
        print(format_ir(result.optimized_ir))
    if args.llvm:
        print(result.llvm_ir)

    if args.o:
        from .runner import build_executable
        build_executable(result.llvm_ir, args.o)
        print(f"Built {args.o}")
    if args.run:
        from .runner import run_llvm_ir
        return run_llvm_ir(result.llvm_ir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
