// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * A brief confetti burst when an annotator finishes a document.
 *
 * Spencer asked for "a little bit of whimsy... just some small effect of like
 * congratulations, you did it", explicitly bounded: "whatever Claude can do in 15
 * minutes that does not complicate your life and make a bug". So: no dependency,
 * no canvas, no animation library — CSS keyframes on a handful of absolutely
 * positioned divs that unmount themselves when the animation ends.
 *
 * Annotation is repetitive work measured in hundreds of documents, which is the
 * case for a reward signal rather than against one. It is also pointer-events:
 * none and honours prefers-reduced-motion, so it cannot get in the way of the
 * next document or trigger anyone's motion sensitivity.
 */

import React, { useEffect, useState } from 'react';

const DURATION_MS = 1400;
const PIECE_COUNT = 14;

// Cloudscape status/chart palette, so the burst reads as part of the product.
const COLORS = ['#037f0c', '#0972d3', '#8c4fff', '#f89256', '#e07941'];

/**
 * Precomputed pieces. Deterministic rather than Math.random: an even fan reads as
 * deliberate, repeated bursts stay visually consistent, and each piece gets a
 * stable identity.
 */
const PIECES = Array.from({ length: PIECE_COUNT }, (_, i) => ({
  id: `piece-${i}`,
  leftPct: 8 + (i * 84) / (PIECE_COUNT - 1),
  delayMs: (i % 5) * 70,
  round: i % 3 === 0,
  color: COLORS[i % COLORS.length],
}));

interface Props {
  /** Changing this to a new truthy value fires one burst. */
  trigger: number;
}

const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

const ReviewCelebration = ({ trigger }: Props): React.JSX.Element | null => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!trigger || prefersReducedMotion()) return undefined;
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), DURATION_MS);
    return () => clearTimeout(timer);
  }, [trigger]);

  if (!visible) return null;

  return (
    <div aria-hidden="true" style={{ position: 'fixed', inset: 0, overflow: 'hidden', pointerEvents: 'none', zIndex: 5000 }}>
      <style>{`
        @keyframes idp-confetti-fall {
          0%   { transform: translateY(-10vh) rotate(0deg); opacity: 1; }
          100% { transform: translateY(60vh) rotate(540deg); opacity: 0; }
        }
      `}</style>
      {PIECES.map(({ id, leftPct, delayMs, round, color }) => {
        return (
          <div
            key={id}
            style={{
              position: 'absolute',
              top: 0,
              left: `${leftPct}%`,
              width: 8,
              height: 8,
              borderRadius: round ? '50%' : '2px',
              background: color,
              animation: `idp-confetti-fall ${DURATION_MS}ms ease-in ${delayMs}ms forwards`,
            }}
          />
        );
      })}
    </div>
  );
};

export default ReviewCelebration;
