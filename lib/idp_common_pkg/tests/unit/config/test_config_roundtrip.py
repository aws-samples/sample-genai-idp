# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Export/import round-trip + combined-format-migration tests.

Covers the config-export (minimal diff) -> re-import path and the case where a
config carries BOTH a legacy attribute-list `classes` schema AND a v0.5 assessment
block (two independent migrations must compose). See
.claude/plans/config-v06-migration-and-test-plan.md (T11, T13).
"""

from idp_common.config.merge_utils import (
    get_diff_dict,
    load_system_defaults,
    merge_config_with_defaults,
)
from idp_common.config.migrations.v05_to_v06 import migrate_v05_to_v06
from idp_common.config.models import IDPConfig


class TestExportImportRoundTrip:
    def test_minimal_export_reimports_without_drift(self):
        """T13 — default full config -> minimal diff -> re-merge reproduces the config.

        A `format=minimal` export computes get_diff_dict(defaults, config); re-importing
        deep-merges that diff back onto defaults. For an unmodified config the diff is
        empty and the re-merge must byte-reproduce the merged config.
        """
        defaults = load_system_defaults("pattern-2")
        # A user who customized a couple of fields.
        customized = merge_config_with_defaults(
            {
                "extraction": {
                    "confidence": {"mode": "integrated", "list_batch_size": 40}
                }
            },
            pattern="pattern-2",
        )

        # Export as minimal (only the diff vs defaults).
        minimal = get_diff_dict(defaults, customized)
        # The diff should carry the customizations and NOT the whole config.
        assert minimal["extraction"]["confidence"]["mode"] == "integrated"
        assert "ocr" not in minimal  # unchanged sections are omitted

        # Re-import: merge the minimal diff back onto defaults.
        reimported = merge_config_with_defaults(minimal, pattern="pattern-2")

        # Round-trip must reproduce the customized merged config exactly.
        assert (
            IDPConfig(**reimported).model_dump() == IDPConfig(**customized).model_dump()
        )

    def test_v05_config_minimal_export_is_v06_shaped(self):
        """A v0.5 fixture, once loaded/migrated, exports minimal in v0.6 shape (no
        top-level `assessment`; differences live under extraction.confidence/geometry)."""
        v05 = {
            "assessment": {
                "model": "us.anthropic.claude-opus-4-8",
                "geometry_mode": "llm_only",
            }
        }
        defaults = load_system_defaults("pattern-2")
        merged = merge_config_with_defaults(v05, pattern="pattern-2")  # migrates first
        minimal = get_diff_dict(defaults, merged)

        assert "assessment" not in minimal
        assert (
            minimal["extraction"]["confidence"]["model"]
            == "us.anthropic.claude-opus-4-8"
        )
        assert minimal["extraction"]["geometry"]["mode"] == "llm"


class TestCombinedFormatMigration:
    def test_v05_assessment_block_and_extraction_delta_compose(self):
        """T11 — a config with a v0.5 assessment block AND an extraction delta migrates
        cleanly: assessment folds into extraction.confidence and the extraction delta is
        preserved (the two don't collide)."""
        cfg = {
            "assessment": {
                "model": "us.anthropic.claude-opus-4-8",
                "inshard_list_batch_size": 30,
            },
            "extraction": {
                "model": "us.anthropic.claude-sonnet-4-6",  # a real extraction override
                "assessment_integration": "integrated",
            },
        }
        out = migrate_v05_to_v06(cfg)
        assert "assessment" not in out
        assert out["extraction"]["model"] == "us.anthropic.claude-sonnet-4-6"
        assert (
            out["extraction"]["confidence"]["model"] == "us.anthropic.claude-opus-4-8"
        )
        assert out["extraction"]["confidence"]["list_batch_size"] == 30
        assert out["extraction"]["confidence"]["mode"] == "integrated"
        # Full validation succeeds through IDPConfig.
        full = IDPConfig(**merge_config_with_defaults(cfg, pattern="pattern-2"))
        assert full.extraction.model == "us.anthropic.claude-sonnet-4-6"
        assert full.extraction.confidence.model == "us.anthropic.claude-opus-4-8"
