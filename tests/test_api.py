from fastapi.testclient import TestClient

from backend import app as api

client = TestClient(api.app)


def post(code, **extra):
    return client.post("/api/compile", json={"code": code, **extra}).json()


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_compile_and_run_returns_all_stages():
    data = post("make x be 2\nsay x plus 3")
    assert data["ok"] and data["output"] == "5\n" and data["runError"] is None
    for key in ("tokens", "ast", "ir", "optimizedIr", "llvm", "stats"):
        assert data[key]
    assert data["stats"]["after"] < data["stats"]["before"]


def test_optimize_flag_changes_ir_not_output():
    on = post("say 1 plus 2", optimize=True)
    off = post("say 1 plus 2", optimize=False)
    assert on["output"] == off["output"] == "3\n"
    assert off["stats"]["after"] == off["stats"]["before"]


def test_compile_only_does_not_run():
    data = post("say 1", run=False)
    assert data["ok"] and data["output"] == ""


def test_type_errors_are_all_returned_with_positions():
    data = post("say a\nsay b")
    assert not data["ok"] and len(data["errors"]) == 2
    assert data["errors"][0]["line"] == 1 and "hasn't been made" in data["errors"][0]["message"]


def test_syntax_error():
    data = post("make x 5")
    assert not data["ok"] and "`be`" in data["errors"][0]["message"]


def test_infinite_loop_is_stopped(monkeypatch):
    monkeypatch.setattr(api, "RUN_TIMEOUT_SECONDS", 1)
    data = post("make x be 0\nwhile true\n change x to x plus 1\ndone")
    assert "stopped" in data["runError"]


def test_divide_by_zero_is_a_clear_runtime_error():
    for optimize in (True, False):
        data = post("say 1\nmake z be 0\nsay 1 divided by z\nsay 2", optimize=optimize)
        assert data["output"] == "1\nRuntime error: you divided by zero.\n"
        assert data["runError"]


def test_oversized_source_rejected():
    response = client.post("/api/compile", json={"code": "x" * 30_000})
    assert response.status_code == 422
