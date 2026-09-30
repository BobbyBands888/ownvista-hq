// ffmpeg helpers (installed on the runner only when Villa Studio has work).
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export function run(cmd, args, { timeoutMs = 600000 } = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    const timer = setTimeout(() => { p.kill('SIGKILL'); reject(new Error(`${cmd} timed out`)); }, timeoutMs);
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { err += d; if (err.length > 200000) err = err.slice(-100000); });
    p.on('error', (e) => { clearTimeout(timer); reject(e); });
    p.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) return resolve({ out, err });
      const e = new Error(`${cmd} exited ${code}: ${err.slice(-800)}`);
      e.stderr = err;
      reject(e);
    });
  });
}

export async function hasFfmpeg() {
  try { await run('ffmpeg', ['-version']); return true; } catch { return false; }
}

export const workdir = () => mkdtemp(join(tmpdir(), 'vc-'));

// Read duration/size from `ffmpeg -i` (works even where ffprobe isn't installed).
export async function probe(file) {
  const err = await run('ffmpeg', ['-hide_banner', '-i', file]).then((r) => r.err, (e) => e.stderr || e.message);
  const d = /Duration:\s*(\d+):(\d+):([\d.]+)/.exec(err);
  const v = /Stream #[^\n]*Video:[^\n]*?\b(\d{2,5})x(\d{2,5})\b/.exec(err);
  return {
    duration: d ? +d[1] * 3600 + +d[2] * 60 + +d[3] : 0,
    width: v ? +v[1] : null,
    height: v ? +v[2] : null,
    hasAudio: /Stream #[^\n]*Audio:/.test(err),
  };
}

// Extract n JPEG frames spread across the clip → data URIs for the vision model.
export async function framesAsDataUris(file, n = 3) {
  const dir = await workdir();
  const { duration } = await probe(file);
  const uris = [];
  for (let i = 0; i < n; i++) {
    const t = Math.max(0, Math.min(duration - 0.1, ((i + 0.5) / n) * duration));
    const outFile = join(dir, `f${i}.jpg`);
    await run('ffmpeg', ['-y', '-ss', t.toFixed(2), '-i', file, '-frames:v', '1', '-vf', 'scale=768:-2', '-q:v', '4', outFile]);
    uris.push(`data:image/jpeg;base64,${(await readFile(outFile)).toString('base64')}`);
  }
  return uris;
}

const FONT = [
  process.env.FFMPEG_FONT,
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  '/System/Library/Fonts/Supplemental/Arial.ttf',
  '/Library/Fonts/Arial.ttf',
].find((f) => f && existsSync(f));
const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/:/g, '\\:').replace(/'/g, '’').replace(/%/g, '\\%');

async function card(dir, name, lines, { w, h, seconds = 3 }) {
  const out = join(dir, `${name}.mp4`);
  const size = Math.round(h / 16);
  const draws = lines.map((l, i) => {
    const fs = i === 0 ? size : Math.round(size * 0.55);
    const y = `(h/2)+${Math.round((i - (lines.length - 1) / 2) * size * 1.4)}-text_h/2`;
    return `drawtext=fontfile=${FONT}:text='${esc(l)}':fontcolor=white@0.92:fontsize=${fs}:x=(w-text_w)/2:y=${y}`;
  });
  const vf = [...draws, `fade=t=in:st=0:d=0.6`, `fade=t=out:st=${seconds - 0.6}:d=0.6`].join(',');
  await run('ffmpeg', ['-y', '-f', 'lavfi', '-i', `color=c=0x0b0b0c:s=${w}x${h}:r=24:d=${seconds}`, '-vf', vf, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '24', out]);
  return out;
}

/**
 * Stitch clips into one film with title + end cards and licensed music.
 * clips: local mp4 paths in order. Returns the output path. Targets < maxBytes (Supabase free: 50 MB/file).
 */
export async function stitchFilm({ clips, title, subtitle, endLines, musicFile, w = 1920, h = 1080, maxBytes = 45 * 1024 * 1024 }) {
  const dir = await workdir();
  const norm = [];
  for (const [i, c] of clips.entries()) {
    const out = join(dir, `n${i}.mp4`);
    const { duration } = await probe(c);
    const d = Math.max(1, duration);
    await run('ffmpeg', ['-y', '-i', c, '-an',
      '-vf', `scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2:color=0x0b0b0c,setsar=1,fps=24,fade=t=in:st=0:d=0.4,fade=t=out:st=${(d - 0.4).toFixed(2)}:d=0.4`,
      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', out]);
    norm.push(out);
  }
  const titleCard = await card(dir, 'title', [title, subtitle].filter(Boolean), { w, h });
  const endCard = await card(dir, 'end', endLines, { w, h });
  const list = join(dir, 'list.txt');
  await writeFile(list, [titleCard, ...norm, endCard].map((f) => `file '${f}'`).join('\n'));
  const silent = join(dir, 'silent.mp4');
  await run('ffmpeg', ['-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', silent]);
  const { duration } = await probe(silent);

  // Two-pass bitrate targeting to stay under the storage limit.
  const audioKbps = 160;
  const videoKbps = Math.max(1500, Math.floor(((maxBytes * 8) / duration) / 1000 * 0.94) - audioKbps);
  const final = join(dir, 'film.mp4');
  const passlog = join(dir, 'pass');
  await run('ffmpeg', ['-y', '-i', silent, '-c:v', 'libx264', '-preset', 'medium', '-b:v', `${videoKbps}k`, '-pass', '1', '-passlogfile', passlog, '-an', '-f', 'mp4', '/dev/null']);
  const audioArgs = musicFile
    ? ['-stream_loop', '-1', '-i', musicFile]
    : ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo'];
  await run('ffmpeg', ['-y', '-i', silent, ...audioArgs,
    '-map', '0:v:0', '-map', '1:a:0',
    '-af', `afade=t=in:st=0:d=1.5,afade=t=out:st=${Math.max(0, duration - 2.5).toFixed(2)}:d=2.5,volume=0.85`,
    '-c:v', 'libx264', '-preset', 'medium', '-b:v', `${videoKbps}k`, '-pass', '2', '-passlogfile', passlog,
    '-c:a', 'aac', '-b:a', `${audioKbps}k`, '-shortest', '-movflags', '+faststart', final]);
  const { size } = await stat(final);
  return { path: final, bytes: size, duration };
}
