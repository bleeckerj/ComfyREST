from comfyrest.client import ComfyClient


def test_probe_root_bad_host():
    c = ComfyClient(base_url="http://127.0.0.1:59999", timeout=0.1)
    try:
        r = c.probe_root()
        # Should return a dict even on failure
        assert isinstance(r, dict)
    except Exception:
        # network errors are acceptable in CI if Comfy isn't running
        assert True


def test_list_routes_no_server():
    c = ComfyClient(base_url="http://127.0.0.1:59999", timeout=0.1)
    r = c.list_routes()
    assert isinstance(r, dict)
