from proofkit.extractor import extract_claims

def test_maps_tests_claim():
    claims = extract_claims("All done, tests pass.", root=".")
    assert any(c.strategy == "tests" for c in claims)

def test_maps_build_claim():
    claims = extract_claims("The build is clean.", root=".")
    assert any(c.strategy == "build" for c in claims)

def test_maps_http_claim():
    claims = extract_claims("GET http://localhost:8000/health returns 200.", root=".")
    http = [c for c in claims if c.strategy == "http"][0]
    assert "localhost:8000/health" in http.command

def test_unmappable_returns_empty():
    assert extract_claims("Looks nice.", root=".") == []
