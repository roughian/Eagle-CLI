import unittest
from unittest.mock import Mock

from cli_anything.eagle.core.client import EagleClient


class DummyResponse:
    def __init__(self, payload, status_code=200, url="http://localhost/test"):
        self._payload = payload
        self.status_code = status_code
        self.url = url
        self.reason = "OK"

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class EagleClientTests(unittest.TestCase):
    def test_build_url_normalizes_relative_paths(self):
        client = EagleClient(base_url="http://localhost:41595/")
        self.assertEqual(client._build_url("/api/item/list"), "http://localhost:41595/api/item/list")

    def test_constructor_starts_without_a_session(self):
        client = EagleClient()
        self.assertIsNone(client._session)

    def test_detect_prefers_v1_when_available(self):
        session = Mock()
        session.get.side_effect = [
            DummyResponse({"status": "success", "data": {"version": "4.0.0"}}),
            DummyResponse({"status": "success", "data": {"version": "4.0.0"}}),
            DummyResponse({"status": "error", "message": "method not allowed"}, status_code=404),
        ]
        client = EagleClient(session=session)
        result = client.detect()
        self.assertTrue(result.root_available)
        self.assertTrue(result.v1_available)
        self.assertFalse(result.v2_available)
        self.assertEqual(result.inferred_variant, "v1")

    def test_item_update_sends_expected_payload(self):
        session = Mock()
        session.request.return_value = DummyResponse({"status": "success", "data": {"id": "abc"}})
        client = EagleClient(session=session)
        client.item_update("abc", tags=["ref"], annotation="note", url="https://eagle.cool", star=5)
        session.request.assert_called_once()
        kwargs = session.request.call_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["json"]["id"], "abc")
        self.assertEqual(kwargs["json"]["tags"], ["ref"])
        self.assertEqual(kwargs["json"]["star"], 5)


if __name__ == "__main__":
    unittest.main()
