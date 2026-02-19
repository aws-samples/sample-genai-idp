# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for DynamoDB configuration compression (Issue #200).

Verifies that:
- Config data is compressed when writing to DynamoDB
- Compressed data is correctly decompressed when reading
- Legacy inline (uncompressed) items are read correctly (backward compat)
- Large configurations with many document classes can be stored
- Metadata fields remain as top-level DynamoDB attributes
- Round-trip: write → read returns identical data
"""

import gzip
import json
from unittest.mock import Mock, patch

from idp_common.config.configuration_manager import (
    _COMPRESSED_DATA_FIELD,
    _COMPRESSED_STORAGE_MARKER,
    _COMPRESSED_STORAGE_VALUE,
    ConfigurationManager,
)


class TestCompressItem:
    """Tests for _compress_item static method."""

    def test_compress_produces_compressed_marker(self):
        """Compressed item must have the storage marker."""
        item = {
            "Configuration": "Config#v1",
            "IsActive": False,
            "Description": "test",
            "ocr": {"backend": "textract"},
            "classes": [],
        }
        result = ConfigurationManager._compress_item(item)
        assert result[_COMPRESSED_STORAGE_MARKER] == _COMPRESSED_STORAGE_VALUE

    def test_compress_produces_binary_data(self):
        """Compressed item must have binary config data."""
        item = {
            "Configuration": "Config#v1",
            "ocr": {"backend": "textract"},
            "classes": [{"id": "doc1"}],
        }
        result = ConfigurationManager._compress_item(item)
        assert _COMPRESSED_DATA_FIELD in result
        assert isinstance(result[_COMPRESSED_DATA_FIELD], bytes)

    def test_compress_preserves_metadata_as_toplevel(self):
        """Metadata fields must remain as top-level DynamoDB attributes."""
        item = {
            "Configuration": "Config#v1",
            "IsActive": True,
            "Description": "my version",
            "CreatedAt": "2024-01-01T00:00:00Z",
            "UpdatedAt": "2024-06-01T00:00:00Z",
            "ocr": {"backend": "textract"},
            "classes": [],
        }
        result = ConfigurationManager._compress_item(item)

        assert result["Configuration"] == "Config#v1"
        assert result["IsActive"] is True
        assert result["Description"] == "my version"
        assert result["CreatedAt"] == "2024-01-01T00:00:00Z"
        assert result["UpdatedAt"] == "2024-06-01T00:00:00Z"

    def test_compress_removes_config_from_toplevel(self):
        """Config data should NOT be in top-level after compression."""
        item = {
            "Configuration": "Config#v1",
            "ocr": {"backend": "textract"},
            "classes": [{"id": "doc1"}],
            "extraction": {"model": "test"},
        }
        result = ConfigurationManager._compress_item(item)

        # Config keys should not be in the top-level
        assert "ocr" not in result
        assert "classes" not in result
        assert "extraction" not in result

    def test_compress_data_is_valid_gzip(self):
        """The compressed data should be valid gzip that decompresses to JSON."""
        item = {
            "Configuration": "Schema",
            "notes": "test schema",
            "classes": [{"$id": "doc1", "type": "object"}],
        }
        result = ConfigurationManager._compress_item(item)

        # Decompress and verify it's valid JSON
        decompressed = gzip.decompress(result[_COMPRESSED_DATA_FIELD])
        parsed = json.loads(decompressed.decode("utf-8"))
        assert parsed["notes"] == "test schema"
        assert len(parsed["classes"]) == 1

    def test_compress_reduces_size(self):
        """Compression should significantly reduce size for repetitive config data."""
        # Build a config with many similar document classes (mimics real-world)
        classes = []
        for i in range(50):
            classes.append(
                {
                    "$id": f"document-class-{i}",
                    "type": "object",
                    "x-aws-idp-document-type": f"Type {i}",
                    "properties": {
                        f"field_{j}": {
                            "type": "string",
                            "description": f"Description of field {j} for document class {i}",
                        }
                        for j in range(20)
                    },
                    "required": [f"field_{j}" for j in range(10)],
                }
            )

        item = {
            "Configuration": "Config#v1",
            "classes": classes,
            "ocr": {"backend": "textract"},
            "classification": {"model": "test-model"},
            "extraction": {"model": "test-model"},
        }

        # Get raw size
        raw_json = json.dumps(item, default=str)
        raw_size = len(raw_json.encode("utf-8"))

        result = ConfigurationManager._compress_item(item)
        compressed_size = len(result[_COMPRESSED_DATA_FIELD])

        # Should achieve at least 5x compression on repetitive JSON
        assert compressed_size < raw_size / 5, (
            f"Expected >5x compression but got {raw_size / compressed_size:.1f}x "
            f"({raw_size:,} → {compressed_size:,} bytes)"
        )


class TestDecompressItem:
    """Tests for _decompress_item static method."""

    def test_decompress_compressed_item(self):
        """Should correctly decompress a compressed item."""
        config_data = {"ocr": {"backend": "textract"}, "classes": [{"id": "doc1"}]}
        compressed_bytes = gzip.compress(json.dumps(config_data).encode("utf-8"))

        item = {
            "Configuration": "Config#v1",
            "IsActive": True,
            "Description": "test",
            _COMPRESSED_STORAGE_MARKER: _COMPRESSED_STORAGE_VALUE,
            _COMPRESSED_DATA_FIELD: compressed_bytes,
        }

        result = ConfigurationManager._decompress_item(item)

        assert result["Configuration"] == "Config#v1"
        assert result["IsActive"] is True
        assert result["Description"] == "test"
        assert result["ocr"] == {"backend": "textract"}
        assert result["classes"] == [{"id": "doc1"}]
        # Compression markers should not be in the result
        assert _COMPRESSED_STORAGE_MARKER not in result
        assert _COMPRESSED_DATA_FIELD not in result

    def test_decompress_legacy_inline_item(self):
        """Legacy inline items (no compression marker) should be returned as-is."""
        item = {
            "Configuration": "Config#v1",
            "IsActive": False,
            "ocr": {"backend": "textract"},
            "classes": [],
        }

        result = ConfigurationManager._decompress_item(item)

        # Should be identical (no decompression needed)
        assert result == item

    def test_decompress_handles_bytes_type(self):
        """Should handle raw bytes (not Binary wrapper)."""
        config_data = {"test_key": "test_value"}
        compressed_bytes = gzip.compress(json.dumps(config_data).encode("utf-8"))

        item = {
            "Configuration": "Schema",
            _COMPRESSED_STORAGE_MARKER: _COMPRESSED_STORAGE_VALUE,
            _COMPRESSED_DATA_FIELD: compressed_bytes,  # raw bytes, not Binary
        }

        result = ConfigurationManager._decompress_item(item)
        assert result["test_key"] == "test_value"

    def test_decompress_handles_missing_data_gracefully(self):
        """Should return item as-is if compressed data field is missing."""
        item = {
            "Configuration": "Config#v1",
            _COMPRESSED_STORAGE_MARKER: _COMPRESSED_STORAGE_VALUE,
            # _COMPRESSED_DATA_FIELD is missing
        }

        result = ConfigurationManager._decompress_item(item)
        # Should return original item (graceful degradation)
        assert result == item


class TestCompressionRoundTrip:
    """Tests for compress → decompress round-trip."""

    def test_roundtrip_preserves_all_data(self):
        """Compress then decompress should return the same data."""
        item = {
            "Configuration": "Config#v1",
            "IsActive": True,
            "Description": "my config",
            "CreatedAt": "2024-01-01T00:00:00Z",
            "UpdatedAt": "2024-06-15T12:00:00Z",
            "_config_format": "full",
            "ocr": {"backend": "textract", "features": ["TABLES"]},
            "classification": {"model": "nova-pro", "temperature": 0.1},
            "extraction": {"model": "nova-pro", "temperature": 0.0},
            "assessment": {"enabled": True},
            "classes": [
                {
                    "$id": "invoice",
                    "type": "object",
                    "properties": {"total": {"type": "string"}},
                },
                {
                    "$id": "receipt",
                    "type": "object",
                    "properties": {"amount": {"type": "string"}},
                },
            ],
        }

        compressed = ConfigurationManager._compress_item(item)
        decompressed = ConfigurationManager._decompress_item(compressed)

        # All original fields should be present and equal
        for key, value in item.items():
            assert key in decompressed, f"Missing key after round-trip: {key}"
            assert decompressed[key] == value, (
                f"Value mismatch for key {key}: {decompressed[key]} != {value}"
            )

    def test_roundtrip_with_empty_classes(self):
        """Round-trip with empty classes list."""
        item = {
            "Configuration": "Config#default",
            "classes": [],
            "ocr": {},
        }

        compressed = ConfigurationManager._compress_item(item)
        decompressed = ConfigurationManager._decompress_item(compressed)

        assert decompressed["classes"] == []

    def test_roundtrip_with_special_characters(self):
        """Round-trip with unicode and special characters in config."""
        item = {
            "Configuration": "Config#v1",
            "classes": [
                {
                    "$id": "formulaire-français",
                    "description": "Document avec des caractères spéciaux: é, è, ê, ë, ü, ö, ñ, 中文",
                    "properties": {
                        "montant": {
                            "type": "string",
                            "description": "Le montant total en €",
                        },
                    },
                }
            ],
        }

        compressed = ConfigurationManager._compress_item(item)
        decompressed = ConfigurationManager._decompress_item(compressed)

        assert decompressed["classes"][0]["$id"] == "formulaire-français"
        assert "中文" in decompressed["classes"][0]["description"]


class TestWriteRecordCompression:
    """Integration tests for _write_record with compression."""

    def test_write_record_uses_compression(self):
        """_write_record should store compressed data in DynamoDB."""
        mock_table = Mock()
        mock_table.get_item.return_value = {}

        with patch(
            "idp_common.config.configuration_manager.boto3.resource"
        ) as mock_boto3:
            mock_boto3.return_value.Table.return_value = mock_table

            manager = ConfigurationManager(table_name="test-table")
            manager.save_configuration(
                "Schema",
                {
                    "notes": "test",
                    "classes": [],
                    "classification": {
                        "model": "m",
                        "temperature": 0.1,
                        "top_k": 1,
                        "top_p": 0.1,
                        "max_tokens": 100,
                        "system_prompt": "",
                        "task_prompt": "",
                    },
                    "extraction": {
                        "model": "m",
                        "temperature": 0.1,
                        "top_k": 1,
                        "top_p": 0.1,
                        "max_tokens": 100,
                        "system_prompt": "",
                        "task_prompt": "",
                    },
                },
            )

            # Verify put_item was called with compressed format
            call_args = mock_table.put_item.call_args
            saved_item = call_args[1]["Item"]

            assert saved_item[_COMPRESSED_STORAGE_MARKER] == _COMPRESSED_STORAGE_VALUE
            assert _COMPRESSED_DATA_FIELD in saved_item
            assert isinstance(saved_item[_COMPRESSED_DATA_FIELD], bytes)
            assert saved_item["Configuration"] == "Schema"


class TestReadRecordDecompression:
    """Integration tests for _read_record with decompression."""

    def test_read_record_decompresses_compressed_item(self):
        """_read_record should decompress compressed items from DynamoDB."""
        # Create a compressed item as it would be stored in DynamoDB
        config_data = {
            "config_type": "Schema",
            "notes": "test schema",
            "classes": [],
            "classification": {
                "model": "m",
                "temperature": "0.1",
                "top_k": "1",
                "top_p": "0.1",
                "max_tokens": "100",
                "system_prompt": "",
                "task_prompt": "",
            },
            "extraction": {
                "model": "m",
                "temperature": "0.1",
                "top_k": "1",
                "top_p": "0.1",
                "max_tokens": "100",
                "system_prompt": "",
                "task_prompt": "",
            },
        }
        compressed_bytes = gzip.compress(json.dumps(config_data).encode("utf-8"))

        mock_table = Mock()
        mock_table.get_item.return_value = {
            "Item": {
                "Configuration": "Schema",
                _COMPRESSED_STORAGE_MARKER: _COMPRESSED_STORAGE_VALUE,
                _COMPRESSED_DATA_FIELD: compressed_bytes,
            }
        }

        with patch(
            "idp_common.config.configuration_manager.boto3.resource"
        ) as mock_boto3:
            mock_boto3.return_value.Table.return_value = mock_table

            manager = ConfigurationManager(table_name="test-table")
            config = manager.get_configuration("Schema")

            assert config is not None
            assert config.notes == "test schema"

    def test_read_record_handles_legacy_inline_item(self):
        """_read_record should handle legacy inline items (backward compat)."""
        # Legacy inline item (no compression markers)
        mock_table = Mock()
        mock_table.get_item.return_value = {
            "Item": {
                "Configuration": "Schema",
                "config_type": "Schema",
                "notes": "legacy schema",
                "classes": [],
                "classification": {
                    "model": "m",
                    "temperature": "0.1",
                    "top_k": "1",
                    "top_p": "0.1",
                    "max_tokens": "100",
                    "system_prompt": "",
                    "task_prompt": "",
                },
                "extraction": {
                    "model": "m",
                    "temperature": "0.1",
                    "top_k": "1",
                    "top_p": "0.1",
                    "max_tokens": "100",
                    "system_prompt": "",
                    "task_prompt": "",
                },
            }
        }

        with patch(
            "idp_common.config.configuration_manager.boto3.resource"
        ) as mock_boto3:
            mock_boto3.return_value.Table.return_value = mock_table

            manager = ConfigurationManager(table_name="test-table")
            config = manager.get_configuration("Schema")

            assert config is not None
            assert config.notes == "legacy schema"


class TestLargeConfigCompression:
    """Tests verifying large configs fit within DynamoDB limits after compression."""

    def test_100_classes_fits_after_compression(self):
        """A config with 100 document classes should compress well under 400KB."""
        classes = []
        for i in range(100):
            classes.append(
                {
                    "$id": f"document-class-{i:03d}",
                    "type": "object",
                    "x-aws-idp-document-type": f"document_type_{i}",
                    "x-aws-idp-document-name-regex": f".*class_{i}.*",
                    "properties": {
                        f"field_{j}": {
                            "type": "string",
                            "description": f"This is a description for field number {j} of document class {i}",
                            "x-aws-idp-evaluation-method": "llm",
                        }
                        for j in range(25)
                    },
                    "required": [f"field_{j}" for j in range(15)],
                }
            )

        item = {
            "Configuration": "Config#v1",
            "IsActive": True,
            "Description": "Large config with 100 classes",
            "CreatedAt": "2024-01-01T00:00:00Z",
            "UpdatedAt": "2024-06-01T00:00:00Z",
            "_config_format": "full",
            "classes": classes,
            "ocr": {"backend": "textract"},
            "classification": {"model": "nova-pro", "temperature": 0.0},
            "extraction": {"model": "nova-pro", "temperature": 0.0},
            "assessment": {"enabled": True},
            "summarization": {"enabled": False},
        }

        result = ConfigurationManager._compress_item(item)
        compressed_size = len(result[_COMPRESSED_DATA_FIELD])

        # Must fit within DynamoDB 400KB limit
        assert compressed_size < 400 * 1024, (
            f"100-class config compressed to {compressed_size:,} bytes, "
            f"exceeds 400KB DynamoDB limit"
        )

        # Verify round-trip
        decompressed = ConfigurationManager._decompress_item(result)
        assert len(decompressed["classes"]) == 100

    def test_500_classes_fits_after_compression(self):
        """A config with 500 document classes should still fit after compression."""
        classes = []
        for i in range(500):
            classes.append(
                {
                    "$id": f"doc-class-{i:04d}",
                    "type": "object",
                    "x-aws-idp-document-type": f"type_{i}",
                    "properties": {
                        f"f_{j}": {
                            "type": "string",
                            "description": f"Field {j} desc for class {i}",
                        }
                        for j in range(15)
                    },
                    "required": [f"f_{j}" for j in range(8)],
                }
            )

        item = {
            "Configuration": "Config#v1",
            "classes": classes,
            "ocr": {"backend": "textract"},
            "classification": {"model": "test"},
            "extraction": {"model": "test"},
        }

        result = ConfigurationManager._compress_item(item)
        compressed_size = len(result[_COMPRESSED_DATA_FIELD])

        assert compressed_size < 400 * 1024, (
            f"500-class config compressed to {compressed_size:,} bytes, "
            f"exceeds 400KB DynamoDB limit"
        )

        # Verify round-trip
        decompressed = ConfigurationManager._decompress_item(result)
        assert len(decompressed["classes"]) == 500
