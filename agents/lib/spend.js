// Every paid API call goes through here. The database decides (vc_reserve_spend):
// $20 per paid order incl. 2K upgrade and retries, $25/week on samples, $150/month backstop.
import { db } from './db.js';

export class SpendRefused extends Error {
  constructor(reason) { super(`Spend refused: ${reason}`); this.name = 'SpendRefused'; this.reason = reason; }
}

export async function reserve({ orderId, clipId = null, purpose, amount, note = null }) {
  const r = await db.rpc('vc_reserve_spend', {
    p_order: orderId, p_clip: clipId, p_purpose: purpose, p_amount: amount, p_note: note,
  });
  if (!r?.ok) throw new SpendRefused(r?.reason || 'unknown');
  return r.id;
}

// Draw a concrete charge out of an earlier reservation (the pre-reserved 2K upgrade budget).
export async function split({ reservationId, amount, purpose, clipId, note }) {
  const r = await db.rpc('vc_split_spend', { p_id: reservationId, p_amount: amount, p_purpose: purpose, p_clip: clipId, p_note: note });
  if (!r?.ok) throw new SpendRefused(r?.reason || 'reservation exhausted');
  return r.id;
}

export const settle = (id, actual, ref) => db.rpc('vc_settle_spend', { p_id: id, p_actual: actual, p_ref: ref });
export const release = (id) => db.rpc('vc_release_spend', { p_id: id });
