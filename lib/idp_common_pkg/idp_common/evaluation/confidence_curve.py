# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Confidence→accuracy curve: the engine behind the review-effort estimator.

The estimator answers "how many documents must a human review to reach 99%
accuracy?" That number is only meaningful if we know ``P(correct | confidence)``
for *this* test set — the probability that a field labeled at a given confidence
is actually right. This module owns that curve: its representation, how it is
built from observations, how it blends with a prior when observations are
scarce, and the estimate it produces.

**Why a reliability table rather than a fitted model.** The curve is stored as
per-bin empirical accuracy — the same shape Stickler's ``ECEMetric`` emits. It is
explainable (you can show a user the bins), needs no inference-time dependency,
serializes to a few hundred bytes of DynamoDB, and composes additively: folding
in new observations is incrementing two counters per bin, which is what makes the
self-correcting updater cheap and idempotent-friendly. Isotonic regression would
be smoother but requires refitting over retained raw observations.

**The load-bearing assumption, and where it fails.** Everything here rests on low
confidence implying a likely error, monotonically. That is a standard modeling
assumption (it underpins active learning), not a guarantee. Two failure modes are
dangerous enough to detect explicitly rather than assume away:

1. *Overconfidence* — the model is wrong **and** confident, so errors hide in the
   high-confidence zone that worst-first review never visits. The estimator
   cannot see these by construction, so it will happily certify a set that is
   not accurate. ``calibration_health`` reports the ECE that reveals this, and
   ``audit_sample_size`` reserves review budget for a random sample of the
   high-confidence zone — the only way to catch it.
2. *Degenerate confidence* — every field scores ~0.9, so there is no worst-first
   signal and the ordering is arbitrary. Note that ECE is near-zero here (a
   single bin is trivially well-calibrated), so ECE alone does **not** catch it;
   ``bin_coverage`` is tracked separately for exactly this reason.

Both surface through ``EstimateConfidence`` so a caller can weaken or refuse the
numbers rather than presenting a prior-driven guess as measurement.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Ten fixed 0.1-wide bins, matching Stickler's ECEMetric bin edges so its output
# folds in without rebinning (and so a reliability table shown in the UI lines up
# with the ECE bins shown next to it).
BIN_COUNT = 10
BIN_WIDTH = 1.0 / BIN_COUNT

# Blending: how many observations in a bin before the measured rate fully
# displaces the prior. Below this the two are blended proportionally, so a bin
# with 2 observations doesn't swing the estimate on noise. This is Bayesian
# shrinkage with a fixed pseudo-count; 20 is a judgment call, chosen so a
# typical worst-first review pass (tens of fields in the low-confidence bins)
# starts to dominate the prior while a handful of reviews does not.
PRIOR_STRENGTH = 20.0

# Below this many total observations the curve is reported as prior-driven
# regardless of distribution — too little data to call anything "measured".
MIN_OBSERVATIONS_FOR_MEASURED = 30

# A curve is only usable for worst-first ordering if confidence actually varies.
# Fewer populated bins than this means the signal is degenerate.
MIN_BINS_FOR_SIGNAL = 3

# Expected Calibration Error above which we consider confidence untrustworthy
# and recommend reviewing everything instead of a small worst-first sample.
ECE_UNRELIABLE_THRESHOLD = 0.15

# Quality tiers. A tier is a claim about a test set's *label* accuracy, so it must
# be earnable and losable from measurement rather than asserted by a user —
# otherwise it is decoration. Expressed as accuracy (1 - baseline_error) because
# that is the question a tier answers: "how good is this ground truth?"
GOLD_ACCURACY = 0.99
SILVER_ACCURACY = 0.95


class QualityTier(str, Enum):
    """A test set's label-quality tier, derived from its measured curve.

    Deliberately not a user-set field. GOLD requires the curve to be genuinely
    measured on this set, because a 99% figure computed from a cross-set prior is
    not evidence about *these* labels.
    """

    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    # Confidence cannot be trusted to rank correctness here (degenerate, or
    # worse-than-chance ranking), so no accuracy claim is defensible — the case a
    # badge must refuse to dress up as Bronze.
    UNRATED = "unrated"


TIER_EXPLANATIONS = {
    QualityTier.GOLD: (
        "at least 99% estimated label accuracy, measured on this test set "
        "(not extrapolated from a prior)"
    ),
    QualityTier.SILVER: (
        "at least 95% estimated label accuracy, with the confidence curve at "
        "least partially measured on this test set"
    ),
    QualityTier.BRONZE: (
        "below 95% estimated label accuracy, or accuracy is still estimated from "
        "a cross-set prior rather than measured here — review or score this set "
        "to earn a higher tier"
    ),
    QualityTier.UNRATED: (
        "confidence cannot be trusted to rank errors on this set, so no accuracy "
        "claim is defensible — reviewing a subset would not be meaningful"
    ),
}


# AUROC below which confidence cannot usefully *rank* correctness, which is the
# only thing worst-first review needs from it. 0.5 is chance; anything at or
# under this is no better than reviewing at random.
#
# This is a separate gate from ECE because the two measure different things and
# can disagree completely. Measured on a 100-document W-2 set: one grader scored
# ECE 0.032 / AUROC 0.480 and another ECE 0.054 / AUROC 0.878 — the *worse* ECE
# had the far better ranking, and the ECE-only gate called the useless one
# reliable. Calibration says "is 0.9 really 90%?"; discrimination says "are the
# wrong answers the ones with low scores?". Only the latter justifies reviewing a
# subset.
AUROC_UNRELIABLE_THRESHOLD = 0.55

# Enough observations to trust an AUROC estimate at all. Below this the ranking
# statistic is noise and the gate would fire on small samples that are simply
# thin rather than genuinely undiscriminating.
MIN_OBSERVATIONS_FOR_AUROC = 100

# Default effort model. Deliberately a flat heuristic: it ignores field
# complexity, document variance and annotator speed. Real per-annotator timings
# should replace this once claim→complete durations are being recorded.
DEFAULT_SECONDS_PER_FIELD = 14.0
DEFAULT_SECONDS_PER_PAGE = 20.0
DEFAULT_FIELDS_PER_DOC = 12.0
DEFAULT_PAGES_PER_DOC = 2.4

# Upper bound on the high-confidence audit sample. See _audit_sample_size for
# the detection-power reasoning behind 30.
AUDIT_SAMPLE_TARGET = 30


def bin_index(confidence: float) -> int:
    """Return the reliability-table bin a confidence value falls in.

    Confidence of exactly 1.0 belongs in the top bin rather than overflowing.
    """
    if confidence <= 0.0:
        return 0
    if confidence >= 1.0:
        return BIN_COUNT - 1
    return min(int(confidence / BIN_WIDTH), BIN_COUNT - 1)


def bin_midpoint(index: int) -> float:
    return (index + 0.5) * BIN_WIDTH


class EstimateConfidence(str, Enum):
    """How much the numbers derived from a curve can be trusted.

    Exposed to the UI so a cold-start estimate is never rendered with the same
    authority as a measured one.
    """

    # No observations for this set: a generic prior is doing all the work.
    PRIOR = "prior"
    # Some review observations, but not enough (or not spread widely enough) to
    # displace the prior.
    PARTIALLY_MEASURED = "partially-measured"
    # Enough observations, spread over enough of the confidence range, that the
    # curve reflects this set.
    MEASURED = "measured"
    # Confidence does not predict correctness here (miscalibrated or
    # degenerate). Worst-first review is not justified.
    UNRELIABLE = "unreliable"


@dataclass
class CalibrationHealth:
    """Whether confidence can be trusted to rank correctness on this set."""

    ece: Optional[float]
    bin_coverage: int
    total_observations: int
    # Set when confidence is present but useless for ordering.
    degenerate: bool = False
    overconfident: bool = False
    # Ranking power: P(a wrong field scores lower than a correct one). None until
    # there are enough observations to estimate it.
    auroc: Optional[float] = None
    # Set when confidence ranks correctness no better than chance. Distinct from
    # `degenerate`: confidence may vary across many bins (so coverage looks
    # healthy) and still put the errors in the wrong places.
    undiscriminating: bool = False

    @property
    def reliable(self) -> bool:
        if self.total_observations == 0:
            return True  # Nothing measured yet — not evidence of a problem.
        return not (self.degenerate or self.overconfident or self.undiscriminating)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ece": self.ece,
            "auroc": self.auroc,
            "binCoverage": self.bin_coverage,
            "totalObservations": self.total_observations,
            "degenerate": self.degenerate,
            "overconfident": self.overconfident,
            "undiscriminating": self.undiscriminating,
            "reliable": self.reliable,
        }


@dataclass
class ConfidenceCurve:
    """A reliability table over confidence bins, plus the prior it blends with.

    ``correct[i]`` / ``total[i]`` are raw counts for bin ``i``, so folding in new
    observations is pure addition and the curve can be rebuilt from, or merged
    with, any other curve over the same bins.
    """

    correct: List[float] = field(default_factory=lambda: [0.0] * BIN_COUNT)
    total: List[float] = field(default_factory=lambda: [0.0] * BIN_COUNT)
    # Optional identity, so a curve is never reused across a config change that
    # shifts what confidence means.
    test_set_id: Optional[str] = None
    config_version: Optional[str] = None
    # Provenance of the observations folded in so far.
    review_observations: int = 0
    scoring_observations: int = 0

    # -- construction ----------------------------------------------------

    @classmethod
    def from_observations(
        cls, observations: Iterable[Tuple[float, bool]], **kwargs: Any
    ) -> "ConfidenceCurve":
        curve = cls(**kwargs)
        curve.add_observations(observations)
        return curve

    def add_observations(
        self, observations: Iterable[Tuple[float, bool]], source: str = "review"
    ) -> int:
        """Fold ``(confidence, correct)`` pairs in. Returns the count accepted.

        Non-finite or out-of-range confidences are dropped rather than clamped:
        a confidence of NaN or 5.0 signals an upstream bug, and silently binning
        it would corrupt the curve in a way that is very hard to trace back.
        """
        accepted = 0
        for confidence, correct in observations:
            if confidence is None:
                continue
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or not (0.0 <= value <= 1.0):
                logger.warning(
                    "Dropping out-of-range confidence observation: %r", confidence
                )
                continue
            index = bin_index(value)
            self.total[index] += 1.0
            if correct:
                self.correct[index] += 1.0
            accepted += 1

        if source == "scoring":
            self.scoring_observations += accepted
        else:
            self.review_observations += accepted
        return accepted

    def add_ece_bins(self, bins: Sequence[Dict[str, Any]]) -> int:
        """Fold in Stickler ``ECEMetric`` bins from a scoring run.

        A scoring run measures correctness across the *whole* confidence range,
        including the high-confidence zone that worst-first review never reaches
        — so this is the highest-fidelity source the curve has.
        """
        accepted = 0
        for entry in bins or []:
            count = entry.get("count") or 0
            if not count:
                continue
            accuracy = entry.get("accuracy")
            if accuracy is None:
                continue
            bin_range = entry.get("range") or []
            if len(bin_range) != 2:
                continue
            # Bin by its own midpoint so Stickler's edges map onto ours even if
            # its bin count were to change.
            index = bin_index((float(bin_range[0]) + float(bin_range[1])) / 2.0)
            self.total[index] += float(count)
            self.correct[index] += float(count) * float(accuracy)
            accepted += int(count)
        self.scoring_observations += accepted
        return accepted

    # -- the curve itself ------------------------------------------------

    @property
    def total_observations(self) -> float:
        return sum(self.total)

    @property
    def bin_coverage(self) -> int:
        """How many bins carry at least one observation."""
        return sum(1 for t in self.total if t > 0)

    def accuracy_at(
        self, confidence: float, prior: Optional["ConfidenceCurve"] = None
    ) -> float:
        """``P(correct | confidence)``, blended with a prior when data is thin.

        With few observations in a bin the measured rate is noise, so it is
        shrunk toward the prior with weight ``n / (n + PRIOR_STRENGTH)``. With no
        prior available the fallback is the bin's own confidence value — i.e.
        "assume the model's confidence is honest", which is the most neutral
        assumption we can make and is exactly what a perfectly calibrated model
        would give.
        """
        index = bin_index(confidence)
        observed_n = self.total[index]
        neutral = bin_midpoint(index)

        prior_rate = neutral
        if prior is not None and prior.total[index] > 0:
            prior_rate = prior.correct[index] / prior.total[index]

        if observed_n <= 0:
            return prior_rate

        observed_rate = self.correct[index] / observed_n
        weight = observed_n / (observed_n + PRIOR_STRENGTH)
        return weight * observed_rate + (1.0 - weight) * prior_rate

    def reliability_table(
        self, prior: Optional["ConfidenceCurve"] = None
    ) -> List[Dict[str, Any]]:
        """Per-bin view for display: the curve users can actually inspect."""
        table = []
        for index in range(BIN_COUNT):
            total = self.total[index]
            table.append(
                {
                    "binStart": round(index * BIN_WIDTH, 2),
                    "binEnd": round((index + 1) * BIN_WIDTH, 2),
                    "observations": int(total),
                    "observedAccuracy": (
                        self.correct[index] / total if total > 0 else None
                    ),
                    "blendedAccuracy": self.accuracy_at(bin_midpoint(index), prior),
                }
            )
        return table

    def calibration_health(self) -> CalibrationHealth:
        """Detect the two failure modes that invalidate worst-first review.

        ECE here is computed against bin midpoints (we keep counts, not raw
        confidences), which is the standard binned ECE estimator.
        """
        total = self.total_observations
        if total <= 0:
            return CalibrationHealth(ece=None, bin_coverage=0, total_observations=0)

        error = 0.0
        for index in range(BIN_COUNT):
            n = self.total[index]
            if n <= 0:
                continue
            observed = self.correct[index] / n
            error += (n / total) * abs(observed - bin_midpoint(index))

        coverage = self.bin_coverage
        # Degenerate: confidence barely varies, so there is nothing to rank by.
        # Checked independently of ECE because a single bin is trivially
        # "well-calibrated" (ECE ~ 0) while being useless for ordering.
        degenerate = (
            coverage < MIN_BINS_FOR_SIGNAL and total >= MIN_OBSERVATIONS_FOR_MEASURED
        )
        # Overconfident: mass sits in high-confidence bins whose observed
        # accuracy is materially worse than claimed — the dangerous quadrant.
        overconfident = (
            error > ECE_UNRELIABLE_THRESHOLD and self._high_confidence_error() > 0.1
        )
        # Undiscriminating: confidence does not rank correctness. This is the
        # failure ECE and bin coverage both miss — spread-out, well-calibrated
        # scores that nonetheless put the errors in the high-confidence end.
        auroc = self.auroc()
        undiscriminating = (
            auroc is not None
            and total >= MIN_OBSERVATIONS_FOR_AUROC
            and auroc <= AUROC_UNRELIABLE_THRESHOLD
        )

        return CalibrationHealth(
            ece=error,
            auroc=auroc,
            bin_coverage=coverage,
            total_observations=int(total),
            degenerate=degenerate,
            overconfident=overconfident,
            undiscriminating=undiscriminating,
        )

    def auroc(self) -> Optional[float]:
        """P(a wrong field scores lower than a correct one), from bin counts.

        The probability that a randomly chosen incorrect field has lower
        confidence than a randomly chosen correct one — exactly what worst-first
        review depends on, and what ECE does not measure.

        Computed from the binned counts we already store rather than raw pairs,
        so it needs no extra state. Ties inside a bin contribute 0.5, which is the
        standard treatment and the reason a single-bin curve scores 0.5 (chance)
        instead of appearing perfect. Returns None when either class is absent —
        with no errors, or nothing correct, ranking is undefined rather than good.

        Binning discards within-bin ordering, so this reads *lower* than an AUROC
        over raw confidences (measured: 0.742 here vs 0.878 from Stickler's
        unbinned ``AUROCMetric`` on the same run). That bias is one-directional
        and therefore safe for a reliability gate — it can call a good ranker
        mediocre, but it will not call a chance-level ranker good. Use Stickler's
        value when reporting AUROC as a metric; use this one for the gate.
        """
        correct_per_bin = [self.correct[i] for i in range(BIN_COUNT)]
        wrong_per_bin = [self.total[i] - self.correct[i] for i in range(BIN_COUNT)]
        n_correct = sum(correct_per_bin)
        n_wrong = sum(wrong_per_bin)
        if n_correct <= 0 or n_wrong <= 0:
            return None

        # Concordant pairs: wrong in a lower bin than correct. Ties count half.
        concordant = 0.0
        for w_index in range(BIN_COUNT):
            w = wrong_per_bin[w_index]
            if w <= 0:
                continue
            higher = sum(correct_per_bin[w_index + 1 :])
            concordant += w * (higher + 0.5 * correct_per_bin[w_index])
        return concordant / (n_correct * n_wrong)

    def _high_confidence_error(self) -> float:
        """Confidence-minus-accuracy gap in the top three bins (>=0.7).

        This is the zone worst-first review never reaches, so a gap here is the
        signal that errors are hiding where the estimator cannot see them.
        """
        weighted, mass = 0.0, 0.0
        for index in range(7, BIN_COUNT):
            n = self.total[index]
            if n <= 0:
                continue
            observed = self.correct[index] / n
            weighted += n * max(0.0, bin_midpoint(index) - observed)
            mass += n
        return weighted / mass if mass > 0 else 0.0

    def assess_estimate_confidence(self) -> EstimateConfidence:
        health = self.calibration_health()
        if not health.reliable:
            return EstimateConfidence.UNRELIABLE
        total = self.total_observations
        if total <= 0:
            return EstimateConfidence.PRIOR
        if (
            total < MIN_OBSERVATIONS_FOR_MEASURED
            or health.bin_coverage < MIN_BINS_FOR_SIGNAL
        ):
            return EstimateConfidence.PARTIALLY_MEASURED
        # Only a scoring run measures the high-confidence zone; review-only
        # observations arrive worst-first and leave that end prior-driven.
        if self.scoring_observations <= 0:
            return EstimateConfidence.PARTIALLY_MEASURED
        return EstimateConfidence.MEASURED

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correct": [float(c) for c in self.correct],
            "total": [float(t) for t in self.total],
            "testSetId": self.test_set_id,
            "configVersion": self.config_version,
            "reviewObservations": int(self.review_observations),
            "scoringObservations": int(self.scoring_observations),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ConfidenceCurve":
        if not data:
            return cls()
        correct = [float(c) for c in (data.get("correct") or [])]
        total = [float(t) for t in (data.get("total") or [])]
        # Tolerate a stored curve with a different bin count rather than
        # crashing: pad or truncate to the current shape.
        correct = (correct + [0.0] * BIN_COUNT)[:BIN_COUNT]
        total = (total + [0.0] * BIN_COUNT)[:BIN_COUNT]
        return cls(
            correct=correct,
            total=total,
            test_set_id=data.get("testSetId"),
            config_version=data.get("configVersion"),
            review_observations=int(data.get("reviewObservations", 0) or 0),
            scoring_observations=int(data.get("scoringObservations", 0) or 0),
        )


def quality_tier(
    baseline_error: float,
    estimate_confidence: "EstimateConfidence",
    calibration: "CalibrationHealth",
) -> "QualityTier":
    """Derive a test set's quality tier from its measured curve.

    Gated on *measurement*, not just on the number: a 99% accuracy computed from a
    cross-set prior says nothing about these labels, so it cannot earn GOLD. An
    unreliable curve is UNRATED rather than a low tier, because the problem is
    that the estimate means nothing — not that the labels are bad.
    """
    if not calibration.reliable:
        return QualityTier.UNRATED

    accuracy = 1.0 - baseline_error
    if accuracy >= GOLD_ACCURACY and estimate_confidence is EstimateConfidence.MEASURED:
        return QualityTier.GOLD
    if accuracy >= SILVER_ACCURACY and estimate_confidence in (
        EstimateConfidence.MEASURED,
        EstimateConfidence.PARTIALLY_MEASURED,
    ):
        return QualityTier.SILVER
    return QualityTier.BRONZE


@dataclass
class ReviewEstimate:
    """What the estimator tells a user, plus how much to trust it."""

    docs_to_review: int
    total_docs: int
    implied_cutoff: Optional[float]
    residual_error: float
    baseline_error: float
    effort_minutes: float
    estimate_confidence: EstimateConfidence
    audit_sample_size: int
    calibration: CalibrationHealth
    # Range rather than a point when the curve is prior-driven, so the UI can
    # avoid implying precision the data doesn't support.
    docs_to_review_low: int
    docs_to_review_high: int
    recommend_review_all: bool
    burndown: List[Dict[str, Any]]

    @property
    def tier(self) -> "QualityTier":
        return quality_tier(
            self.baseline_error, self.estimate_confidence, self.calibration
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "qualityTier": self.tier.value,
            "qualityTierReason": TIER_EXPLANATIONS[self.tier],
            "docsToReview": self.docs_to_review,
            "docsToReviewLow": self.docs_to_review_low,
            "docsToReviewHigh": self.docs_to_review_high,
            "totalDocs": self.total_docs,
            "impliedCutoff": self.implied_cutoff,
            "residualError": self.residual_error,
            "baselineError": self.baseline_error,
            "effortMinutes": self.effort_minutes,
            "estimateConfidence": self.estimate_confidence.value,
            "auditSampleSize": self.audit_sample_size,
            "recommendReviewAll": self.recommend_review_all,
            "calibration": self.calibration.to_dict(),
            "burndown": self.burndown,
        }


def _audit_sample_size(reviewed: int, auto_accepted: int) -> int:
    """How many high-confidence documents to spot-check at random.

    Worst-first review is blind to confident errors by construction, so a
    published set can be certified accurate while the auto-accepted zone is
    quietly wrong. A small random sample from that zone is the only way to catch
    it — and it doubles as the only source of observations for the
    high-confidence end of the curve, which review alone never populates.

    Sized for *detection power*, not as a fraction of review depth: ~30 samples
    gives a better-than-even chance of seeing at least one error if 2%+ of the
    auto-accepted zone is wrong (1 - 0.98^30 ≈ 45%), which is the scale of
    problem worth halting a publish over. Scaling with review depth instead
    would be backwards — the case that most needs auditing is the one where
    almost nothing was reviewed, and that is exactly where a
    proportional-to-reviewed sample would shrink to nothing.

    Capped at 30 (and at 10% of the pool for small pools) so it stays cheap
    insurance rather than a second review pass.
    """
    if auto_accepted <= 0:
        return 0
    target = min(AUDIT_SAMPLE_TARGET, max(5, int(round(0.10 * auto_accepted))))
    return min(target, auto_accepted)


def estimate_for_target(
    curve: ConfidenceCurve,
    target_accuracy: float,
    total_docs: int,
    doc_confidences: Optional[Sequence[float]] = None,
    prior: Optional[ConfidenceCurve] = None,
    fields_per_doc: float = DEFAULT_FIELDS_PER_DOC,
    pages_per_doc: float = DEFAULT_PAGES_PER_DOC,
    seconds_per_field: float = DEFAULT_SECONDS_PER_FIELD,
    seconds_per_page: float = DEFAULT_SECONDS_PER_PAGE,
) -> ReviewEstimate:
    """How many documents must be reviewed to reach ``target_accuracy``?

    Walks the documents worst-confidence-first and accumulates the expected
    number of wrong fields remaining. Reviewing a document is assumed to fix its
    fields, so residual error after reviewing the ``N`` worst is the expected
    error over the *unreviewed* remainder. The answer is the smallest ``N`` whose
    residual error meets the target.

    ``doc_confidences`` is the per-document minimum confidence (what the detail
    page sorts by). Without it the estimate falls back to spreading documents
    evenly across the curve, which is far cruder — the caller should pass real
    values whenever it has them.

    ``target_accuracy`` is a percentage (99.0), matching the UI slider.
    """
    total_docs = max(0, int(total_docs))
    target_error_fraction = max(0.0, (100.0 - float(target_accuracy)) / 100.0)

    if total_docs == 0:
        return ReviewEstimate(
            docs_to_review=0,
            total_docs=0,
            implied_cutoff=None,
            residual_error=0.0,
            baseline_error=0.0,
            effort_minutes=0.0,
            estimate_confidence=curve.assess_estimate_confidence(),
            audit_sample_size=0,
            calibration=curve.calibration_health(),
            docs_to_review_low=0,
            docs_to_review_high=0,
            recommend_review_all=False,
            burndown=[],
        )

    # Worst-first ordering. Documents with no confidence sort first: an unlabeled
    # or unscored document is the least trustworthy thing in the set, not the
    # most.
    if doc_confidences:
        confidences = sorted((-1.0 if c is None else float(c)) for c in doc_confidences)
        # The set may be larger than the sample the caller could afford to read
        # (the queue/estimator cap reads a bounded page). Extrapolate the observed
        # distribution over the rest instead of leaving them unrepresented:
        # without this a 2008-document set sampled at 500 padded the remaining
        # 1508 with the "no confidence" sentinel, which sorts to the front and
        # suppressed impliedCutoff and every burndown cutoff to null.
        if len(confidences) < total_docs:
            measured = [c for c in confidences if c >= 0]
            if measured:
                missing = total_docs - len(confidences)
                # Quantile-preserving fill: repeat the measured distribution so
                # the extrapolated documents share its shape.
                confidences.extend(
                    measured[int(i * len(measured) / missing)] for i in range(missing)
                )
                confidences.sort()
    else:
        # No per-doc confidence: assume documents spread across the curve.
        confidences = [bin_midpoint(i % BIN_COUNT) for i in range(total_docs)]
        confidences.sort()
    confidences = confidences[:total_docs]

    # Expected wrong fields per document at its own confidence.
    per_doc_error = []
    for value in confidences:
        # A document with no confidence data gets the neutral prior rather than
        # being treated as certainly wrong.
        accuracy = curve.accuracy_at(0.5 if value < 0 else value, prior)
        per_doc_error.append(max(0.0, 1.0 - accuracy) * fields_per_doc)

    total_fields = fields_per_doc * len(per_doc_error)
    total_expected_errors = sum(per_doc_error)
    baseline_error = total_expected_errors / total_fields if total_fields > 0 else 0.0

    # Residual error after reviewing the N worst documents, for every N.
    burndown: List[Dict[str, Any]] = []
    residual_by_n: List[float] = []
    remaining = total_expected_errors
    for n in range(len(per_doc_error) + 1):
        residual = remaining / total_fields if total_fields > 0 else 0.0
        residual_by_n.append(residual)
        burndown.append(
            {
                "docsReviewed": n,
                "residualErrorPct": round(residual * 100.0, 4),
                "cutoff": (
                    None
                    if n == 0
                    else (
                        None if confidences[n - 1] < 0 else round(confidences[n - 1], 4)
                    )
                ),
            }
        )
        if n < len(per_doc_error):
            remaining -= per_doc_error[n]

    docs_to_review = len(per_doc_error)
    for n, residual in enumerate(residual_by_n):
        if residual <= target_error_fraction:
            docs_to_review = n
            break

    implied_cutoff = (
        None
        if docs_to_review == 0 or confidences[docs_to_review - 1] < 0
        else round(confidences[docs_to_review - 1], 4)
    )

    seconds = docs_to_review * (
        fields_per_doc * seconds_per_field + pages_per_doc * seconds_per_page
    )
    auto_accepted = total_docs - docs_to_review
    audit = _audit_sample_size(docs_to_review, auto_accepted)
    # The audit sample is real review work, so its cost belongs in the estimate
    # rather than being quietly excluded to make the headline number smaller.
    seconds += audit * (
        fields_per_doc * seconds_per_field + pages_per_doc * seconds_per_page
    )

    estimate_confidence = curve.assess_estimate_confidence()
    calibration = curve.calibration_health()

    # Uncertainty band. A prior-driven estimate could be substantially wrong in
    # either direction, so widen the range rather than implying a point value;
    # it tightens as observations accumulate.
    spread = {
        EstimateConfidence.PRIOR: 0.5,
        EstimateConfidence.PARTIALLY_MEASURED: 0.25,
        EstimateConfidence.MEASURED: 0.1,
        EstimateConfidence.UNRELIABLE: 0.5,
    }[estimate_confidence]
    low = max(0, int(math.floor(docs_to_review * (1.0 - spread))))
    high = min(total_docs, int(math.ceil(docs_to_review * (1.0 + spread))))

    # When confidence doesn't rank correctness, a small worst-first sample is not
    # justified — say so instead of returning a number that looks actionable.
    recommend_review_all = (
        estimate_confidence == EstimateConfidence.UNRELIABLE or not calibration.reliable
    )

    return ReviewEstimate(
        docs_to_review=docs_to_review,
        total_docs=total_docs,
        implied_cutoff=implied_cutoff,
        residual_error=residual_by_n[min(docs_to_review, len(residual_by_n) - 1)],
        baseline_error=baseline_error,
        effort_minutes=seconds / 60.0,
        estimate_confidence=estimate_confidence,
        audit_sample_size=audit,
        calibration=calibration,
        docs_to_review_low=low,
        docs_to_review_high=high,
        recommend_review_all=recommend_review_all,
        burndown=burndown,
    )
