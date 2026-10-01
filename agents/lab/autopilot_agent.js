// Autopilot agent: see agents/lib/autopilot.js. Runs every 15 minutes on the Vercel tick (hourly backup in the job).
import { autoApprove } from '../lib/autopilot.js';

export async function run(ctx) {
  return autoApprove(ctx);
}
