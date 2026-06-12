import threading
import http.server
import functools
from proofkit.strategies.http import verify_http, parse_http_claim


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


# --- Task 10.1 tests: parse_http_claim and body assertion ---

def test_parse_http_claim_extracts_url():
    url, status, body = parse_http_claim(
        "GET http://localhost:3000/health returns 200", {}
    )
    assert url == "http://localhost:3000/health"
    assert status == "200"
    assert body is None


def test_parse_http_claim_extracts_want_body_with_pattern():
    url, status, body = parse_http_claim(
        'GET http://localhost:3000/health returns 200 with "ok"', {}
    )
    assert body == "ok"


def test_parse_http_claim_extracts_want_body_containing():
    url, status, body = parse_http_claim(
        'endpoint returns 200 containing "healthy"', {}
    )
    assert body == "healthy"


def test_parse_http_claim_default_status_200():
    url, status, body = parse_http_claim(
        "GET http://localhost:3000/ works", {}
    )
    assert status == "200"


def test_parse_http_claim_non_200_status():
    url, status, body = parse_http_claim(
        "GET http://localhost:3000/admin returns 404", {}
    )
    assert status == "404"


def test_parse_http_claim_base_url_fallback():
    url, status, body = parse_http_claim(
        "endpoint returns 200", {"http": {"base_url": "http://localhost:8080"}}
    )
    assert url == "http://localhost:8080"


def test_body_match_pass(tmp_path):
    (tmp_path / "health").write_text("ok body content")
    h = _serve(tmp_path)
    port = h.server_address[1]
    r = verify_http(
        f'GET http://127.0.0.1:{port}/health returns 200 with "ok body content"',
        root=str(tmp_path),
    )
    h.shutdown()
    assert r.verdict == "pass"


def test_body_match_fail(tmp_path):
    (tmp_path / "health").write_text("something else")
    h = _serve(tmp_path)
    port = h.server_address[1]
    r = verify_http(
        f'GET http://127.0.0.1:{port}/health returns 200 with "EXPECTED_MISSING"',
        root=str(tmp_path),
    )
    h.shutdown()
    assert r.verdict == "fail"
    # raw_output should include first 2000 chars of body
    assert "something else" in r.raw_output
