"""Web API for the Chill compiler.

    POST /api/compile   { code, optimize, run }  ->  every compiler stage + output
    GET  /api/health

Run from the project root:   uvicorn backend.app:app --reload

Design notes
  * Compiling (lex/parse/check/IR/optimize/LLVM text) is safe, so it runs
    in-process and every stage's output is returned for the UI to display.
  * RUNNING user code is not safe in-process (an infinite loop or a crash
    would take the server down), so it runs in a SUBPROCESS with a timeout
    and an output cap. The server only ever sees the captured text.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from chill.ast_nodes import dump
from chill.compiler import compile_source
from chill.errors import CompileError, CompileErrors
from chill.ir import format_ir

ROOT = Path(__file__).resolve().parent.parent
RUN_TIMEOUT_SECONDS = 5
MAX_OUTPUT_CHARS = 20_000
MAX_SOURCE_CHARS = 20_000

app = FastAPI(title="Chill Compiler API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # the Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompileRequest(BaseModel):
    """Request body. `optimize=False` is the -O0 mode; `run=False` only compiles."""
    code: str = Field(max_length=MAX_SOURCE_CHARS)
    optimize: bool = True
    run: bool = True


def error_to_dict(error):
    """Convert a CompileError into JSON the UI can use (position + message)."""
    return {"message": error.message, "line": error.line,
            "column": error.column, "pretty": error.pretty()}


def count_instructions(program):
    """Total IR instructions, to show the optimizer's effect."""
    return sum(len(b.instrs) for f in program.functions for b in f.blocks)


def run_program(code, optimize):
    """Run a program in a subprocess. Returns (output, error_message_or_None)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "program.chill"
        path.write_text(code)
        command = [sys.executable, "-m", "chill", str(path), "--run"]
        if not optimize:
            command.append("-O0")
        try:
            done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return "", f"Your program ran for more than {RUN_TIMEOUT_SECONDS} seconds " \
                       f"and was stopped. Is there a loop that never ends?"
    output = done.stdout[:MAX_OUTPUT_CHARS]
    if done.returncode < 0:      # killed by a signal (a hard crash)
        return output, "Your program crashed while running."
    if done.returncode != 0:     # e.g. our own "Runtime error: ..." exit(1)
        return output, done.stderr[-500:] or "The program stopped with a runtime error."
    return output, None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/compile")
def compile_endpoint(request: CompileRequest):
    """Compile (and optionally run) a program; return every stage's output."""
    try:
        result = compile_source(request.code, optimize_ir=request.optimize)
    except CompileError as error:
        return {"ok": False, "errors": [error_to_dict(error)]}
    except CompileErrors as errors:
        return {"ok": False, "errors": [error_to_dict(e) for e in errors.errors]}

    response = {
        "ok": True,
        "errors": [],
        "tokens": [{"type": t.type.name, "text": t.text, "line": t.line, "column": t.column}
                   for t in result.tokens],
        "ast": dump(result.ast),
        "ir": format_ir(result.ir),
        "optimizedIr": format_ir(result.optimized_ir),
        "llvm": result.llvm_ir,
        "stats": {"before": count_instructions(result.ir),
                  "after": count_instructions(result.optimized_ir)},
        "output": "",
        "runError": None,
    }
    if request.run:
        response["output"], response["runError"] = run_program(request.code, request.optimize)
    return response
