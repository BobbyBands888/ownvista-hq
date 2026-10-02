// Bobby's rule (Oct 1, 2026): nothing the agents build or sell touches real estate or his license.
// This sweep runs at the start of every Builder and Launcher run and undoes anything that slipped through:
//   - approved business/venture ideas about real estate → rejected (never built, never launched)
//   - their launches (draft, waiting, live) → taken down (page 404s, Stripe link switched off)
import { db } from './db.js';
import { realEstateRisk } from './guard.js';
import { deactivateLink } from './stripe_launch.js';
import { truncate } from './text.js';

const NOTE = 'Rejected automatically: Bobby rule — no real estate, license-related or short-term-rental/landlord products.';

export async function retireRealEstate(ctx) {
  const ideas = await db.select('ideas', {
    kind: 'in.(business,venture)', status: 'in.(proposed,approved,launched)', select: 'id,title,summary,steps,business', limit: 200,
  });
  // Villa Cinema is Bobby's own business (it serves rental managers); its ideas stay with him.
  const bad = ideas.filter((i) => i.business === 'ma-real-estate'
    || (i.business !== 'villa-cinema' && i.business !== 'nashville-buys') && realEstateRisk([i.title, i.summary, ...(i.steps || [])].filter(Boolean).join('\n')));
  let pulled = 0;
  for (const idea of bad) {
    await db.update('ideas', { id: `eq.${idea.id}` }, { status: 'rejected', decided_at: new Date().toISOString(), feedback: NOTE });
    const launches = await db.select('launches', { idea_id: `eq.${idea.id}`, status: 'in.(draft,needs_bobby,waiting_key,live)', select: 'id,payment_link_id' });
    for (const l of launches) {
      if (l.payment_link_id) await deactivateLink(l.payment_link_id).catch(() => {});
      await db.update('launches', { id: `eq.${l.id}` }, { status: 'killed', killed_at: new Date().toISOString(), page_html: null, note: NOTE });
      pulled++;
    }
    await ctx.log('guardrail', `Rejected real-estate idea "${truncate(idea.title, 100)}"${launches.length ? ` and took down ${launches.length} launch(es)` : ''}`, { table: 'ideas', id: idea.id });
  }
  return bad.length ? `rejected ${bad.length} real-estate idea(s)${pulled ? `, took down ${pulled} launch(es)` : ''}` : '';
}
