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


# --- Task 10.3 tests: deployed + URL -> http claim ---

def test_deployed_with_url_emits_http_claim():
    """'deployed' keyword + URL in message -> http claim with URL, expectation '200'."""
    claims = extract_claims(
        "I have deployed the app to https://myapp.example.com and it is live.",
        root=".",
    )
    http_claims = [c for c in claims if c.strategy == "http"]
    assert len(http_claims) >= 1
    h = http_claims[0]
    assert "myapp.example.com" in h.command
    assert h.expectation == "200"


def test_deployed_without_url_does_not_emit_bare_http_claim():
    """'deployed' without any URL should not emit an http claim with an empty command."""
    claims = extract_claims("The app is deployed.", root=".")
    http_claims = [c for c in claims if c.strategy == "http"]
    # If an http claim is emitted, it must have a non-empty command (URL)
    for c in http_claims:
        assert c.command != "", "http claim emitted with empty command for deployed-only message"
