"""Running and building the generated LLVM IR.

Two ways to execute a program:
  * run_llvm_ir:     JIT-compile in memory and call `main` (fast, no linker).
  * build_executable: emit an object file and link a real native binary.

IMPORTANT for the web UI: a JIT runs INSIDE the current process, so an infinite
loop or crash would take the host down. The API therefore runs programs in a
SUBPROCESS with a timeout (`python -m chill file --run`).
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

from llvmlite import binding

from .codegen import init_llvm


def _parse(llvm_ir):
    """Parse and verify LLVM IR text into a module."""
    init_llvm()
    module = binding.parse_assembly(llvm_ir)
    module.verify()
    return module


def _machine(for_object=False):
    """Target machine for this CPU. Object files use position-independent
    code ("pic") so modern linkers produce a clean executable."""
    target = binding.Target.from_default_triple()
    if for_object:
        return target.create_target_machine(reloc="pic", codemodel="default")
    return target.create_target_machine()


def run_llvm_ir(llvm_ir):
    """JIT-compile `llvm_ir` and run its `main`. Returns main's exit code."""
    module = _parse(llvm_ir)
    engine = binding.create_mcjit_compiler(module, _machine())
    engine.finalize_object()
    engine.run_static_constructors()
    main = ctypes.CFUNCTYPE(ctypes.c_int)(engine.get_function_address("main"))
    sys.stdout.flush()
    code = main()
    ctypes.CDLL(None).fflush(None)   # flush C's stdout buffer (printf)
    return code


def build_executable(llvm_ir, out_path):
    """Compile `llvm_ir` to a native executable at `out_path`.

    Steps: LLVM IR -> object file (llvmlite) -> link with the system C
    compiler (`cc`), which supplies printf and the program startup code.

    Raises:
        RuntimeError: if no C compiler is available to do the final link.
    """
    linker = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if linker is None:
        raise RuntimeError("I need a C compiler (cc, gcc, or clang) to link the "
                           "program. Try --run instead, which needs none.")
    object_code = _machine(for_object=True).emit_object(_parse(llvm_ir))
    with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as handle:
        handle.write(object_code)
        object_path = handle.name
    try:
        subprocess.run([linker, object_path, "-o", out_path], check=True)
    finally:
        os.unlink(object_path)
