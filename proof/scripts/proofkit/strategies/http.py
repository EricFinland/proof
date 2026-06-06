import urllib.request
from proofkit.strategies import register
from proofkit.strategies.base import Result


@register("http")
def verify_http(claim, root, command=None, expectation=None):
    url = command
    if not url:
        return Result(claim, "http", "", "no URL in claim", "inconclusive", 0.2)
    want = expectation or "200"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            code = resp.getcode()
            body = resp.read(2000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        code, body = e.code, str(e)
    except Exception as e:
        return Result(claim, "http", url, f"request failed: {e}", "fail")
    verdict = "pass" if str(code) == str(want) else "fail"
    return Result(claim, "http", url, f"HTTP {code}\n{body}", verdict)
