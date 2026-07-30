# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the EmbeddingService."""

import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from idp_common.discovery.embedding_service import EmbeddingResult, EmbeddingService


@pytest.fixture
def mock_bedrock_client():
    """Create a mock BedrockClient."""
    client = MagicMock()
    client.region = "us-east-1"
    return client


@pytest.fixture
def embedding_service(mock_bedrock_client):
    """Create an EmbeddingService with mocked client."""
    return EmbeddingService(
        bedrock_client=mock_bedrock_client,
        model_id="cohere.embed-english-v3",
        max_concurrent=2,
    )


class TestEmbeddingResult:
    """Tests for EmbeddingResult dataclass."""

    def test_to_serializable(self):
        """Test conversion to JSON-serializable dict."""
        result = EmbeddingResult(
            embeddings=np.array([[1.0, 2.0], [3.0, 4.0]]),
            valid_keys=["doc1.pdf", "doc2.png"],
            failed_keys=["bad.pdf"],
            embedding_dim=2,
        )
        serialized = result.to_serializable()

        assert serialized["embeddings_shape"] == [2, 2]
        assert serialized["valid_keys"] == ["doc1.pdf", "doc2.png"]
        assert serialized["failed_keys"] == ["bad.pdf"]
        assert serialized["embedding_dim"] == 2
        assert serialized["num_valid"] == 2
        assert serialized["num_failed"] == 1

    def test_empty_result(self):
        """Test empty EmbeddingResult."""
        result = EmbeddingResult(
            embeddings=np.array([]),
            valid_keys=[],
            failed_keys=["all_failed.pdf"],
            embedding_dim=0,
        )
        serialized = result.to_serializable()
        assert serialized["num_valid"] == 0
        assert serialized["num_failed"] == 1


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    def test_init_defaults(self, mock_bedrock_client):
        """Test default initialization."""
        service = EmbeddingService(bedrock_client=mock_bedrock_client)
        assert service.model_id == EmbeddingService.DEFAULT_MODEL_ID
        assert service.max_concurrent == 5
        assert service.input_type == "search_document"

    def test_init_custom(self, mock_bedrock_client):
        """Test custom initialization."""
        service = EmbeddingService(
            bedrock_client=mock_bedrock_client,
            model_id="amazon.titan-embed-image-v1",
            max_concurrent=10,
            input_type="clustering",
        )
        assert service.model_id == "amazon.titan-embed-image-v1"
        assert service.max_concurrent == 10
        assert service.input_type == "clustering"

    def test_embed_images_from_bytes(self, embedding_service, mock_bedrock_client):
        """Test embedding generation from in-memory bytes."""
        # Create small valid JPEG images
        from PIL import Image

        images = []
        for _ in range(3):
            img = Image.new("RGB", (100, 100), color="red")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            images.append(buf.getvalue())

        # Mock batch embedding response
        mock_bedrock_client.generate_embeddings_batch.return_value = [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ]

        embeddings, valid_indices = embedding_service.embed_images_from_bytes(images)

        assert embeddings.shape == (3, 3)
        assert valid_indices == [0, 1, 2]
        mock_bedrock_client.generate_embeddings_batch.assert_called_once()

    def test_embed_images_from_bytes_with_failures(
        self, embedding_service, mock_bedrock_client
    ):
        """Test embedding with some failures."""
        from PIL import Image

        images = []
        for _ in range(3):
            img = Image.new("RGB", (100, 100), color="blue")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            images.append(buf.getvalue())

        # Second embedding fails (None)
        mock_bedrock_client.generate_embeddings_batch.return_value = [
            [1.0, 2.0],
            None,
            [5.0, 6.0],
        ]

        embeddings, valid_indices = embedding_service.embed_images_from_bytes(images)

        assert embeddings.shape == (2, 2)
        assert valid_indices == [0, 2]

    def test_embed_images_empty_list(self, embedding_service):
        """Test embedding with empty list."""
        embeddings, valid_indices = embedding_service.embed_images_from_bytes([])
        assert embeddings.size == 0
        assert valid_indices == []

    def test_compress_image_bytes_small(self, embedding_service):
        """An already-small, in-dimension image is returned unchanged."""
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color="red").save(buf, format="JPEG")
        small_bytes = buf.getvalue()

        # max_size larger than the data and within MAX_IMAGE_DIMENSION → no re-encode
        result = embedding_service._compress_image_bytes(
            small_bytes, max_size=len(small_bytes) + 1000
        )
        assert result == small_bytes

    def test_compress_pil_image(self, embedding_service):
        """Test PIL image compression."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="green")
        result = embedding_service._compress_pil_image(img)
        assert result is not None
        assert len(result) > 0

    def test_compress_pil_image_rgba(self, embedding_service):
        """Test PIL image with alpha channel conversion."""
        from PIL import Image

        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        result = embedding_service._compress_pil_image(img)
        assert result is not None

    def test_embed_document_images_no_valid(
        self, embedding_service, mock_bedrock_client
    ):
        """Test embedding when no documents can be loaded."""
        with patch.object(
            embedding_service,
            "_download_and_prepare_image",
            return_value=None,
        ):
            result = embedding_service.embed_document_images(
                bucket="test-bucket",
                s3_keys=["bad1.xyz", "bad2.xyz"],
            )
            assert len(result.valid_keys) == 0
            assert len(result.failed_keys) == 2

    def test_embed_document_images_success(
        self, embedding_service, mock_bedrock_client
    ):
        """Test successful document image embedding."""
        fake_image = b"fake_jpeg_data"

        with patch.object(
            embedding_service,
            "_download_and_prepare_image",
            return_value=fake_image,
        ):
            mock_bedrock_client.generate_embeddings_batch.return_value = [
                [1.0, 2.0],
                [3.0, 4.0],
            ]

            result = embedding_service.embed_document_images(
                bucket="test-bucket",
                s3_keys=["doc1.pdf", "doc2.png"],
            )

            assert len(result.valid_keys) == 2
            assert result.embeddings.shape == (2, 2)
            assert result.embedding_dim == 2
