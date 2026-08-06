# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the DiscoveryAgent and related tool classes."""

import io
from unittest.mock import MagicMock

import numpy as np
import pytest

from idp_common.discovery.clustering_service import ClusteringService, ClusterResult
from idp_common.discovery.discovery_agent import (
    ClusterAnalysisTool,
    ClusterSchemaOutput,
    DiscoveredClass,
    DiscoveryAgent,
    DocumentVisualTool,
)


@pytest.fixture
def sample_cluster_result():
    """Create a sample ClusterResult for testing."""
    embeddings = np.array(
        [
            [1.0, 0.0, 0.0],
            [1.1, 0.1, 0.0],
            [0.0, 1.0, 0.0],
            [0.1, 1.1, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.1, 1.1],
        ]
    )
    labels = np.array([0, 0, 1, 1, 2, 2])

    from scipy.spatial import KDTree

    return ClusterResult(
        cluster_labels=labels,
        num_clusters=3,
        cluster_sizes={0: 2, 1: 2, 2: 2},
        centroids={
            0: embeddings[0:2].mean(axis=0),
            1: embeddings[2:4].mean(axis=0),
            2: embeddings[4:6].mean(axis=0),
        },
        embeddings=embeddings,
        kdtree=KDTree(embeddings),
    )


@pytest.fixture
def clustering_service():
    """Create a ClusteringService for testing."""
    return ClusteringService(min_cluster_size=2, num_sample_documents=3)


class TestDiscoveredClass:
    """Tests for DiscoveredClass."""

    def test_to_dict(self):
        """Test serialization."""
        dc = DiscoveredClass(
            cluster_id=0,
            classification="Invoice",
            json_schema={"type": "object", "properties": {}},
            document_count=10,
            sample_doc_ids=[0, 1, 2],
        )
        d = dc.to_dict()
        assert d["cluster_id"] == 0
        assert d["classification"] == "Invoice"
        assert d["document_count"] == 10
        assert d["error"] is None

    def test_to_dict_with_error(self):
        """Test serialization with error."""
        dc = DiscoveredClass(
            cluster_id=1,
            classification="Error_Cluster_1",
            json_schema={"error": "failed"},
            document_count=5,
            sample_doc_ids=[],
            error="LLM timeout",
        )
        d = dc.to_dict()
        assert d["error"] == "LLM timeout"


class TestClusterSchemaOutput:
    """Tests for ClusterSchemaOutput Pydantic model."""

    def test_valid_output(self):
        """Test creating valid structured output."""
        output = ClusterSchemaOutput(
            json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            classification="Invoice",
        )
        assert output.classification == "Invoice"
        assert output.json_schema["type"] == "object"

    def test_model_dump(self):
        """Test model serialization."""
        output = ClusterSchemaOutput(
            json_schema={"type": "object"},
            classification="W2",
        )
        d = output.model_dump()
        assert "json_schema" in d
        assert "classification" in d


class TestClusterAnalysisTool:
    """Tests for ClusterAnalysisTool."""

    def test_get_docids_by_distance(self, sample_cluster_result, clustering_service):
        """Test getting document IDs by distance to centroid."""
        tool = ClusterAnalysisTool(sample_cluster_result, clustering_service)
        result = tool.get_cluster_docids_by_distance_to_centroid(
            cluster_id=0, max_docs=10
        )

        assert result["status"] == "success"
        content = result["content"][0]["json"]
        assert content["cluster_id"] == 0
        assert content["total_documents"] == 2
        assert len(content["documents"]) == 2


class TestDocumentVisualTool:
    """Tests for DocumentVisualTool."""

    def test_get_existing_image(self):
        """Test getting an existing document image."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()

        tool = DocumentVisualTool(images={0: image_bytes, 1: image_bytes})
        result = tool.get_document_image(0)

        assert result["status"] == "success"
        assert "image" in result["content"][0]

    def test_get_missing_image(self):
        """Test getting a non-existent document image."""
        tool = DocumentVisualTool(images={})
        result = tool.get_document_image(99)

        assert result["status"] == "error"

    def test_compress_small_image(self):
        """A small, in-dimension image passes through compression unchanged."""
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (50, 50), color="blue").save(buf, format="JPEG")
        small_data = buf.getvalue()

        tool = DocumentVisualTool(images={})
        result = tool._compress_image(small_data, max_size=1024 * 1024)
        assert result == small_data


class TestDiscoveryAgent:
    """Tests for DiscoveryAgent."""

    def test_init_defaults(self):
        """Test default initialization."""
        agent = DiscoveryAgent()
        assert agent.analysis_model_id == "us.anthropic.claude-sonnet-4-6"
        assert agent.max_sample_size == 5
        assert agent.max_workers == 3

    def test_init_custom(self):
        """Test custom initialization."""
        mock_client = MagicMock()
        mock_client.region = "eu-west-1"
        agent = DiscoveryAgent(
            analysis_model_id="us.amazon.nova-pro-v1:0",
            bedrock_client=mock_client,
            max_sample_size=3,
            max_workers=5,
        )
        assert agent.analysis_model_id == "us.amazon.nova-pro-v1:0"
        assert agent.max_sample_size == 3
        assert agent.region == "eu-west-1"

    def test_load_system_prompt_custom(self):
        """Test loading custom system prompt."""
        agent = DiscoveryAgent(system_prompt="Custom prompt here")
        prompt = agent._load_system_prompt()
        assert prompt == "Custom prompt here"

    def test_load_system_prompt_template(self):
        """Test loading system prompt from Jinja2 template."""
        agent = DiscoveryAgent(max_sample_size=7)
        prompt = agent._load_system_prompt()
        assert "7" in prompt
        assert "JSON Schema" in prompt

    def test_reflect(self, sample_cluster_result, clustering_service):
        """Test reflection report generation with mocked Bedrock."""
        mock_client = MagicMock()
        mock_client.region = "us-east-1"
        mock_client.invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {
                        "content": [
                            {"text": "# Reflection Report\n\nAll schemas look good."}
                        ]
                    }
                }
            }
        }
        mock_client.extract_text_from_response.return_value = (
            "# Reflection Report\n\nAll schemas look good."
        )

        agent = DiscoveryAgent(bedrock_client=mock_client)
        classes = [
            DiscoveredClass(
                cluster_id=0,
                classification="Invoice",
                json_schema={"type": "object"},
                document_count=10,
                sample_doc_ids=[0, 1],
            ),
        ]

        report = agent.reflect(classes)
        assert "Reflection Report" in report
        mock_client.invoke_model.assert_called_once()
