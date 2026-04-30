"""Tests for setup/create_endpoint.py — all SDK calls mocked, no live workspace needed."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import setup.create_endpoint as ce


class TestEndpointExists(unittest.TestCase):
    def test_returns_true_when_endpoint_found(self):
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.return_value = MagicMock(name="ep")
        self.assertTrue(ce.endpoint_exists(mock_client, "ep"))

    def test_returns_false_when_endpoint_raises(self):
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.side_effect = Exception("Not found")
        self.assertFalse(ce.endpoint_exists(mock_client, "ep"))


class TestResolveEndpoint(unittest.TestCase):
    def test_returns_dedicated_endpoint_if_exists(self):
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.return_value = MagicMock()
        result = ce.resolve_endpoint(mock_client)
        self.assertEqual(result, ce.ENDPOINT_NAME)

    def test_falls_back_to_system_endpoint(self):
        mock_client = MagicMock()

        def side_effect(name):
            if name == ce.ENDPOINT_NAME:
                raise Exception("Not found")
            return MagicMock()

        mock_client.serving_endpoints.get.side_effect = side_effect
        result = ce.resolve_endpoint(mock_client)
        self.assertEqual(result, ce.SYSTEM_ENDPOINT_NAME)

    def test_raises_when_neither_endpoint_found(self):
        mock_client = MagicMock()
        mock_client.serving_endpoints.get.side_effect = Exception("Not found")
        with self.assertRaises(RuntimeError):
            ce.resolve_endpoint(mock_client)


class TestWriteEndpointName(unittest.TestCase):
    def test_writes_endpoint_name_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "endpoint_name.txt")
            ce.write_endpoint_name("databricks-claude-sonnet-4-6", output_path=out)
            content = pathlib.Path(out).read_text()
        self.assertEqual(content, "databricks-claude-sonnet-4-6\n")


if __name__ == "__main__":
    unittest.main()
