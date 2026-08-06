# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the ConfBench noise-variant catalog and size tiers.

The numbers in variants.py drive the cost estimate an admin approves before
committing to up to 32.71 GB of transfer and storage, so they are asserted here
rather than trusted.
"""

import os

import pytest
import variants


@pytest.mark.unit
class TestCatalogIntegrity:
    def test_variant_count_is_21_not_18(self):
        """The dataset card and PR #583 both say 18; the real count is 21.

        Five variants are partial (they cover 20-46 of the 75 source documents
        rather than all 75), which is how a per-document reading undercounts the
        distinct pipelines.
        """
        assert len(variants.VARIANTS) == 21

    def test_totals_match_declared_constants(self):
        files, nbytes = variants.totals(variants.VARIANTS)
        assert files == variants.TOTAL_FILES == 1346
        assert nbytes == variants.TOTAL_BYTES == 32_713_674_359

    def test_every_variant_has_positive_files_and_bytes(self):
        for name, (files, nbytes) in variants.VARIANTS.items():
            assert files > 0, f"{name} has no files"
            assert nbytes > 0, f"{name} has no bytes"

    def test_variants_ordered_smallest_first(self):
        """Insertion order is part of the contract — the UI renders it directly,
        so the cheap options must lead."""
        sizes = [nbytes for _, nbytes in variants.VARIANTS.values()]
        assert sizes == sorted(sizes)

    def test_original_is_the_clean_baseline(self):
        assert "original" in variants.VARIANTS
        files, nbytes = variants.VARIANTS["original"]
        assert files == 75, "all 75 source documents should have a clean version"
        # ~0.02 GB — the whole point of offering it as its own tier.
        assert nbytes < 50_000_000

    def test_every_variant_has_a_note(self):
        for name in variants.VARIANTS:
            note = variants.variant_note(name)
            assert note and isinstance(note, str)

    def test_partial_variants_are_labelled_as_partial(self):
        """A variant covering fewer than 75 documents must say so — otherwise a
        user comparing accuracy across variants silently compares different
        document populations."""
        for name, (files, _) in variants.VARIANTS.items():
            if files < 75:
                assert "partial" in variants.variant_note(name).lower(), (
                    f"{name} covers only {files} documents but its note does not "
                    f"say 'partial'"
                )


@pytest.mark.unit
class TestTiers:
    def test_all_tiers_reference_known_variants(self):
        for tier_id in variants.TIERS:
            # Raises KeyError on an unknown name.
            variants.totals(variants.tier_variants(tier_id))

    def test_tier_sizes_increase_monotonically(self):
        order = ["clean", "light", "representative", "full"]
        sizes = [variants.totals(variants.tier_variants(t))[1] for t in order]
        assert sizes == sorted(sizes)

    def test_full_tier_is_the_whole_dataset(self):
        files, nbytes = variants.totals(variants.tier_variants("full"))
        assert files == variants.TOTAL_FILES
        assert nbytes == variants.TOTAL_BYTES

    def test_clean_tier_is_tiny(self):
        """The cheap entry point must actually be cheap, or the tier is pointless."""
        _, nbytes = variants.totals(variants.tier_variants("clean"))
        assert nbytes < 50_000_000  # < 0.05 GB

    def test_every_tier_includes_the_clean_baseline(self):
        """Degradation is only interpretable against an undegraded control."""
        for tier_id in variants.TIERS:
            assert "original" in variants.tier_variants(tier_id), (
                f"tier {tier_id} has no clean control arm"
            )

    def test_representative_tier_spans_the_severity_range(self):
        """Its purpose is spread, not cheapness — assert it actually spans."""
        selected = variants.tier_variants("representative")
        per_doc = [variants.VARIANTS[v][1] / variants.VARIANTS[v][0] for v in selected]
        # Heaviest member should be at least 20x the average per-document size
        # of the lightest, or we are not sampling a range at all.
        assert max(per_doc) / min(per_doc) > 20

    def test_tier_test_set_ids_are_unique(self):
        ids = [spec["testSetId"] for spec in variants.TIERS.values()]
        assert len(ids) == len(set(ids))

    def test_full_tier_uses_the_bare_confbench_id(self):
        """Keeps the primary test set's name matching the dataset's own name."""
        assert variants.TIERS["full"]["testSetId"] == "confbench"


@pytest.mark.unit
class TestResolveSelection:
    def test_tier_takes_precedence_over_variants(self):
        test_set_id, resolved = variants.resolve_selection("clean", ["custom15"])
        assert test_set_id == "confbench-clean"
        assert resolved == ["original"]

    def test_handpicked_set_matching_a_tier_targets_that_tier(self):
        """Re-selecting the same set twice must hit one test set, not accumulate
        near-duplicates in Test Studio."""
        tier_list = variants.tier_variants("light")
        test_set_id, _ = variants.resolve_selection(None, list(reversed(tier_list)))
        assert test_set_id == "confbench-light"

    def test_arbitrary_selection_gets_the_custom_id(self):
        test_set_id, resolved = variants.resolve_selection(
            None, ["original", "custom15"]
        )
        assert test_set_id == variants.CUSTOM_TEST_SET_ID
        # Sorted, not input order — resolve_selection normalizes so that the
        # tier-matching comparison is order-insensitive.
        assert resolved == ["custom15", "original"]

    def test_selection_is_deduplicated_and_sorted(self):
        _, resolved = variants.resolve_selection(
            None, ["custom15", "original", "custom15"]
        )
        assert resolved == ["custom15", "original"]

    def test_empty_selection_is_rejected(self):
        with pytest.raises(ValueError, match="tier or a non-empty"):
            variants.resolve_selection(None, [])

    def test_unknown_variant_is_rejected(self):
        """A typo must fail loudly rather than silently ingesting less than the
        caller asked for."""
        with pytest.raises(KeyError, match="Unknown ConfBench noise variant"):
            variants.resolve_selection(None, ["original", "archetype99"])

    def test_unknown_tier_raises(self):
        with pytest.raises(KeyError):
            variants.resolve_selection("enormous", None)


@pytest.mark.unit
class TestCatalogPayload:
    def test_payload_shape(self):
        payload = variants.catalog()
        assert payload["totalFiles"] == variants.TOTAL_FILES
        assert payload["totalBytes"] == variants.TOTAL_BYTES
        assert len(payload["variants"]) == 21
        assert len(payload["tiers"]) == len(variants.TIERS)
        assert payload["source"] == "huggingface:amazon/ConfBench"

    def test_every_variant_entry_is_complete(self):
        for entry in variants.catalog()["variants"]:
            assert set(entry) == {"name", "files", "bytes", "note"}

    def test_tier_entries_carry_precomputed_totals(self):
        for entry in variants.catalog()["tiers"]:
            expected = variants.totals(entry["variants"])
            assert (entry["files"], entry["bytes"]) == expected

    def test_payload_is_json_serializable(self):
        import json

        json.dumps(variants.catalog())


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("CONFBENCH_NETWORK_TESTS") != "1",
    reason="Set CONFBENCH_NETWORK_TESTS=1 to verify the catalog against HuggingFace",
)
def test_catalog_matches_published_dataset():
    """Re-derive the whole table from the live dataset and diff it.

    Guards the failure mode that matters: upstream re-publishes ConfBench, our
    committed sizes go stale, and the UI quietly shows a wrong cost estimate.
    """
    result = variants.verify_against_hub()
    assert result["matches"], "Catalog drift:\n" + "\n".join(result["differences"])
    assert result["observedFiles"] == variants.TOTAL_FILES
    assert result["observedBytes"] == variants.TOTAL_BYTES
