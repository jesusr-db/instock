"""Tests for setup/create_endpoint.py — all SDK calls mocked, no live workspace needed."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import setup.create_endpoint as ce


class TestEndpointExists(unittest.TestCase):
    def test_skips_creation_if_endpoint_exists(self):
        """endpoint_exists() returns True when serving_endpoints.get() succeeds."""
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.return_value = MagicMock(name=ce.ENDPOINT_NAME)
        self.assertTrue(ce.endpoint_exists(mock_client))

    def test_endpoint_not_found_returns_false(self):
        """endpoint_exists() returns False when serving_endpoints.get() raises."""
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.side_effect = Exception("Not found")
        self.assertFalse(ce.endpoint_exists(mock_client))


class TestCreateEndpoint(unittest.TestCase):
    def test_creates_endpoint_with_claude_foundation_model(self):
        """create_endpoint() POSTs to the REST API with the correct endpoint name and entity."""
        mock_client = MagicMock()
        mock_client.config.host = "https://fake.databricks.com"
        mock_client.config.authenticate = MagicMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_response) as mock_post:
            ce.create_endpoint(mock_client)

        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["name"], ce.ENDPOINT_NAME)
        entity = payload["config"]["served_entities"][0]
        self.assertEqual(entity["entity_name"], ce.ENTITY_NAME)


class TestWriteEndpointName(unittest.TestCase):
    def test_writes_endpoint_name_to_file(self):
        """write_endpoint_name() writes 'instockcv-gateway\\n' to the specified path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "endpoint_name.txt")
            ce.write_endpoint_name(output_path=out)
            content = pathlib.Path(out).read_text()
        self.assertEqual(content, "instockcv-gateway\n")


class TestWaitForReady(unittest.TestCase):
    def test_raises_on_timeout(self):
        """wait_for_ready() raises EndpointTimeoutError when timeout=0 and endpoint is not READY."""
        mock_client = MagicMock()
        state_mock = MagicMock()
        state_mock.ready = "NOT_READY"
        state_mock.config_update = None
        mock_client.serving_endpoints.get.return_value = MagicMock(state=state_mock)

        with self.assertRaises(ce.EndpointTimeoutError):
            ce.wait_for_ready(mock_client, timeout=0)


if __name__ == "__main__":
    unittest.main()
