// MiniMax pay-as-you-go prices, verified 2026-09-30 at platform.minimax.io/docs/pricing/overview.
// Re-verify if MiniMax changes pricing; the spend caps are enforced in the database regardless.
export const PRICES = {
  h3_768p_per_sec: 0.08,          // MiniMax-H3 output, 768P
  h3_2k_per_sec: 0.13,            // MiniMax-H3 output, 2K (not used: we upgrade via regeneration)
  regen_output_per_sec: 0.05,     // MiniMax-H3-Regeneration output (768P → 2K)
  regen_input_video_per_sec: 0.05,// regeneration bills the input video again
  extra_image: 0.04,              // first 5 input images free; we send 1 per clip
  regen_extra_image: 0.025,
};

export const CLIP_SECONDS = 5;

export const clipCost = (seconds = CLIP_SECONDS) => +(seconds * PRICES.h3_768p_per_sec).toFixed(4);
// Effective 2K upgrade price is $0.10/s: $0.05 output + $0.05 input video.
export const upgradeCost = (seconds = CLIP_SECONDS) =>
  +(seconds * (PRICES.regen_output_per_sec + PRICES.regen_input_video_per_sec)).toFixed(4);

// Film plan per order kind. Paid: generate at 768P, QA, then upgrade passing clips to 2K.
export function plan(kind) {
  const clips = kind === 'sample' ? 8 : 10;
  const base = clips * clipCost();
  const upgrade = kind === 'sample' ? 0 : clips * upgradeCost();
  return { clips, seconds: CLIP_SECONDS, base: +base.toFixed(2), upgrade: +upgrade.toFixed(2), total: +(base + upgrade).toFixed(2) };
}
