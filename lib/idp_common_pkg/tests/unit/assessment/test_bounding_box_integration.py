# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for bounding box integration in AssessmentService.
"""

import pytest

from idp_common.assessment.service import AssessmentService


class TestBoundingBoxIntegration:
    """Test bounding box functionality in AssessmentService."""

    def test_convert_bbox_to_geometry_valid_coordinates(self):
        """Test conversion from bbox coordinates to geometry format."""
        service = AssessmentService()

        # Test normal coordinates
        bbox_coords = [100, 200, 300, 400]  # x1, y1, x2, y2 in 0-1000 scale
        page_num = 1

        result = service._convert_bbox_to_geometry(bbox_coords, page_num)

        expected = {
            "boundingBox": {
                "top": 0.2,  # y1/1000
                "left": 0.1,  # x1/1000
                "width": 0.2,  # (x2-x1)/1000
                "height": 0.2,  # (y2-y1)/1000
            },
            "page": 1,
        }

        assert result == expected

    def test_convert_bbox_to_geometry_reversed_coordinates(self):
        """Test that coordinates are corrected when reversed."""
        service = AssessmentService()

        # Test with reversed coordinates (x2 < x1, y2 < y1)
        bbox_coords = [300, 400, 100, 200]  # Reversed
        page_num = 2

        result = service._convert_bbox_to_geometry(bbox_coords, page_num)

        # Should be corrected to proper order
        expected = {
            "boundingBox": {
                "top": 0.2,  # min(y1,y2)/1000
                "left": 0.1,  # min(x1,x2)/1000
                "width": 0.2,  # (max(x)-min(x))/1000
                "height": 0.2,  # (max(y)-min(y))/1000
            },
            "page": 2,
        }

        assert result == expected

    def test_convert_bbox_to_geometry_invalid_coordinates(self):
        """Test error handling for invalid coordinate count."""
        service = AssessmentService()

        # Test with wrong number of coordinates
        bbox_coords = [100, 200, 300]  # Only 3 coordinates
        page_num = 1

        with pytest.raises(ValueError, match="Expected 4 coordinates"):
            service._convert_bbox_to_geometry(bbox_coords, page_num)

    def test_extract_geometry_from_assessment_with_bbox_data(self):
        """Test extraction of geometry data from assessment response."""
        service = AssessmentService()

        assessment_data = {
            "account_number": {
                "confidence": 0.95,
                "confidence_reason": "Clear text with high OCR confidence",
                "bbox": [100, 200, 300, 400],
                "page": 1,
            },
            "account_balance": {
                "confidence": 0.88,
                "confidence_reason": "Good text quality",
                "bbox": [400, 500, 600, 550],
                "page": 1,
            },
        }

        result = service._extract_geometry_from_assessment(assessment_data)

        # Check that bbox/page data was converted to geometry format
        assert "geometry" in result["account_number"]
        assert "bbox" not in result["account_number"]
        assert "page" not in result["account_number"]

        # Check geometry structure
        geometry = result["account_number"]["geometry"][0]
        assert "boundingBox" in geometry
        assert "page" in geometry
        assert geometry["page"] == 1

        # Check bounding box values
        bbox = geometry["boundingBox"]
        assert bbox["top"] == 0.2  # 200/1000
        assert bbox["left"] == 0.1  # 100/1000
        assert bbox["width"] == 0.2  # (300-100)/1000
        assert bbox["height"] == 0.2  # (400-200)/1000

    def test_extract_geometry_from_assessment_without_bbox_data(self):
        """Test that assessment data without bbox passes through unchanged."""
        service = AssessmentService()

        assessment_data = {
            "account_number": {
                "confidence": 0.95,
                "confidence_reason": "Clear text with high OCR confidence",
                # No bbox or page data
            }
        }

        result = service._extract_geometry_from_assessment(assessment_data)

        # Should pass through unchanged
        assert result == assessment_data
        assert "geometry" not in result["account_number"]

    def test_extract_geometry_from_assessment_invalid_bbox_format(self):
        """Test handling of invalid bbox format."""
        service = AssessmentService()

        assessment_data = {
            "account_number": {
                "confidence": 0.95,
                "confidence_reason": "Clear text",
                "bbox": "invalid_format",  # Invalid format
                "page": 1,
            }
        }

        result = service._extract_geometry_from_assessment(assessment_data)

        # Should remove invalid bbox data but keep confidence info
        assert "geometry" not in result["account_number"]
        assert "bbox" not in result["account_number"]
        assert "page" not in result["account_number"]
        assert result["account_number"]["confidence"] == 0.95

    def test_extract_geometry_from_assessment_missing_page(self):
        """Test handling when bbox exists but page is missing."""
        service = AssessmentService()

        assessment_data = {
            "account_number": {
                "confidence": 0.95,
                "confidence_reason": "Clear text",
                "bbox": [100, 200, 300, 400],
                # Missing page
            }
        }

        result = service._extract_geometry_from_assessment(assessment_data)

        # Should not create geometry without page info
        assert "geometry" not in result["account_number"]
        assert "bbox" not in result["account_number"]
        assert result["account_number"]["confidence"] == 0.95

    def test_extract_geometry_from_assessment_edge_coordinates(self):
        """Test conversion with edge case coordinates."""
        service = AssessmentService()

        assessment_data = {
            "top_left_field": {
                "confidence": 0.9,
                "confidence_reason": "Located at top-left",
                "bbox": [0, 0, 100, 100],  # Top-left corner
                "page": 1,
            },
            "bottom_right_field": {
                "confidence": 0.85,
                "confidence_reason": "Located at bottom-right",
                "bbox": [900, 900, 1000, 1000],  # Bottom-right corner
                "page": 2,
            },
        }

        result = service._extract_geometry_from_assessment(assessment_data)

        # Check top-left field
        top_left_geometry = result["top_left_field"]["geometry"][0]
        assert top_left_geometry["boundingBox"]["top"] == 0.0
        assert top_left_geometry["boundingBox"]["left"] == 0.0
        assert top_left_geometry["boundingBox"]["width"] == 0.1
        assert top_left_geometry["boundingBox"]["height"] == 0.1
        assert top_left_geometry["page"] == 1

        # Check bottom-right field
        bottom_right_geometry = result["bottom_right_field"]["geometry"][0]
        assert bottom_right_geometry["boundingBox"]["top"] == 0.9
        assert bottom_right_geometry["boundingBox"]["left"] == 0.9
        assert bottom_right_geometry["boundingBox"]["width"] == 0.1
        assert bottom_right_geometry["boundingBox"]["height"] == 0.1
        assert bottom_right_geometry["page"] == 2
