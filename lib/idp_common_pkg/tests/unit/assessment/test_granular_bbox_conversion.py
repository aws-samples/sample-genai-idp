# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test to verify that both regular and granular assessment services
handle bounding box conversion correctly.
"""

from idp_common.assessment.granular_service import GranularAssessmentService
from idp_common.assessment.service import AssessmentService


def test_both_services_convert_bbox_to_geometry():
    """Test that both regular and granular services convert bbox to geometry."""

    # Test data with bbox coordinates
    mock_assessment_data = {
        "YTDNetPay": {
            "confidence": 1.0,
            "confidence_reason": "Clear text with high OCR confidence",
            "bbox": [443, 333, 507, 345],
            "page": 1,
        },
        "CompanyAddress": {
            "State": {
                "confidence": 0.99,
                "confidence_reason": "Clear text",
                "bbox": [230, 116, 259, 126],
                "page": 1,
            },
            "ZipCode": {
                "confidence": 0.99,
                "confidence_reason": "Clear text",
                "bbox": [261, 116, 298, 126],
                "page": 1,
            },
        },
    }

    print("=== Testing Bounding Box Conversion in Both Services ===")

    # Test regular assessment service
    print("\n📝 Testing Regular AssessmentService")
    regular_service = AssessmentService()
    regular_result = regular_service._extract_geometry_from_assessment(
        mock_assessment_data
    )

    # Check YTDNetPay conversion
    regular_ytd = regular_result["YTDNetPay"]
    regular_ytd_has_geometry = "geometry" in regular_ytd
    regular_ytd_has_bbox = "bbox" in regular_ytd

    print(
        f"Regular Service - YTDNetPay: geometry={regular_ytd_has_geometry}, bbox={regular_ytd_has_bbox}"
    )

    # Check CompanyAddress.State conversion
    regular_state = regular_result["CompanyAddress"]["State"]
    regular_state_has_geometry = "geometry" in regular_state
    regular_state_has_bbox = "bbox" in regular_state

    print(
        f"Regular Service - CompanyAddress.State: geometry={regular_state_has_geometry}, bbox={regular_state_has_bbox}"
    )

    # Test granular assessment service
    print("\n📝 Testing GranularAssessmentService")
    granular_service = GranularAssessmentService()
    granular_result = granular_service._extract_geometry_from_assessment(
        mock_assessment_data
    )

    # Check YTDNetPay conversion
    granular_ytd = granular_result["YTDNetPay"]
    granular_ytd_has_geometry = "geometry" in granular_ytd
    granular_ytd_has_bbox = "bbox" in granular_ytd

    print(
        f"Granular Service - YTDNetPay: geometry={granular_ytd_has_geometry}, bbox={granular_ytd_has_bbox}"
    )

    # Check CompanyAddress.State conversion
    granular_state = granular_result["CompanyAddress"]["State"]
    granular_state_has_geometry = "geometry" in granular_state
    granular_state_has_bbox = "bbox" in granular_state

    print(
        f"Granular Service - CompanyAddress.State: geometry={granular_state_has_geometry}, bbox={granular_state_has_bbox}"
    )

    # Verify both services work identically
    print("\n🔍 Verification:")

    # Both should convert bbox to geometry
    assert (
        regular_ytd_has_geometry
    ), "Regular service should convert YTDNetPay bbox to geometry"
    assert (
        not regular_ytd_has_bbox
    ), "Regular service should remove YTDNetPay bbox after conversion"
    assert (
        granular_ytd_has_geometry
    ), "Granular service should convert YTDNetPay bbox to geometry"
    assert (
        not granular_ytd_has_bbox
    ), "Granular service should remove YTDNetPay bbox after conversion"

    # Both should handle nested attributes
    assert (
        regular_state_has_geometry
    ), "Regular service should convert nested State bbox to geometry"
    assert (
        not regular_state_has_bbox
    ), "Regular service should remove nested State bbox after conversion"
    assert (
        granular_state_has_geometry
    ), "Granular service should convert nested State bbox to geometry"
    assert (
        not granular_state_has_bbox
    ), "Granular service should remove nested State bbox after conversion"

    # Check geometry values are equivalent
    regular_ytd_geometry = regular_ytd["geometry"][0]["boundingBox"]
    granular_ytd_geometry = granular_ytd["geometry"][0]["boundingBox"]

    assert (
        regular_ytd_geometry == granular_ytd_geometry
    ), "Both services should produce identical geometry"

    print("✅ Regular AssessmentService: Converts bbox → geometry correctly")
    print("✅ GranularAssessmentService: Converts bbox → geometry correctly")
    print("✅ Both services handle nested attributes (CompanyAddress.State)")
    print("✅ Both services produce identical geometry output")
    print("✅ Both services remove raw bbox data after conversion")

    print("\n🎉 Both services now support automatic bounding box conversion!")
    print("Your deployed stack with granular assessment will now work correctly!")

    return True


if __name__ == "__main__":
    test_both_services_convert_bbox_to_geometry()
