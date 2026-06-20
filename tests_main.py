import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("ETHERSCAN_API_KEY", "test-key")

import main


class DummyRequest:
    def __init__(self, payload, client_ip="127.0.0.1"):
        self._payload = payload
        self.headers = {"x-forwarded-for": client_ip}
        self.client = type("Client", (), {"host": client_ip})()

    async def json(self):
        return self._payload


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        return DummyResponse({"result": {"0xabc": {"token_name": "Test Token", "token_symbol": "TST", "contract_address": "0xabc"}}})


class AnalyzeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.license_cache.clear()

    async def _run_analyze(self, payload):
        with patch("main.httpx.AsyncClient", DummyAsyncClient), patch.object(
            main.groq_client.chat.completions,
            "create",
            return_value=type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": type("Message", (), {"content": '{"risk_score": 10, "explanation": "ok", "recommendation": "SAFE"}'})()})()]},
            )(),
        ):
            return await main.analyze(DummyRequest(payload))

    async def test_first_free_scan_allows_request_without_license(self):
        result = await self._run_analyze({"contract_address": "0xabc", "chain_id": "1"})
        self.assertFalse(result["is_licensed"])
        self.assertEqual(result["ai_report"]["recommendation"], "SAFE")

    async def test_second_free_scan_is_blocked_for_same_ip(self):
        await self._run_analyze({"contract_address": "0xabc", "chain_id": "1"})
        with self.assertRaises(main.HTTPException) as cm:
            await self._run_analyze({"contract_address": "0xabc", "chain_id": "1"})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.detail, "free_limit_reached")

    async def test_license_key_allows_request(self):
        with patch.object(main, "validate_gumroad_license", AsyncMock(return_value=True)):
            result = await self._run_analyze({"contract_address": "0xabc", "chain_id": "1", "license_key": "abc123"})
        self.assertTrue(result["is_licensed"])


if __name__ == "__main__":
    unittest.main()
