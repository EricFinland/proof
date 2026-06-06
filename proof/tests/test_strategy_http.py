import threading
import http.server
import functools
from proofkit.strategies.http import verify_http


def _serve(tmp):
    h = http.server.HTTPServer(
        ("127.0.0.1", 0),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp)),
    )
    threading.Thread(target=h.serve_forever, daemon=True).start()
    return h


def test_http_200(tmp_path):
    (tmp_path / "health").write_text("ok")
    h = _serve(tmp_path)
    port = h.server_address[1]
    r = verify_http(
        "endpoint works",
        root=".",
        command=f"http://127.0.0.1:{port}/health",
        expectation="200",
    )
    h.shutdown()
    assert r.verdict == "pass"


def test_http_missing_is_fail(tmp_path):
    h = _serve(tmp_path)
    port = h.server_address[1]
    r = verify_http(
        "endpoint works",
        root=".",
        command=f"http://127.0.0.1:{port}/nope",
        expectation="200",
    )
    h.shutdown()
    assert r.verdict == "fail"
