"""Badge SVG endpoint tests."""
import secrets
from tests.conftest import register_and_verify


def test_badge_svg_success(test_client):
    _, _, node_id = register_and_verify(test_client)
    resp = test_client.get(f"/v1/node/{node_id}/badge.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert "<svg" in resp.text
    assert node_id in resp.text


def test_badge_svg_not_found(test_client):
    resp = test_client.get(f"/v1/node/nonexistent-{secrets.token_hex(4)}/badge.svg")
    assert resp.status_code == 404
