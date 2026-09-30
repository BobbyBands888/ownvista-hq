(() => {
  const params = new URLSearchParams(location.search);
  const order = params.get('o');
  const token = params.get('t');
  const $ = (id) => document.getElementById(id);
  const cfg = window.HQ_CONFIG || {};
  let files = [];

  const say = (t) => { $('msg').textContent = t; };
  if (!order || !token) {
    say('This link is missing its order code. Please use the link from our email.');
    $('files').disabled = true;
    return;
  }

  $('files').addEventListener('change', (e) => {
    files = [...e.target.files].slice(0, 30);
    $('list').innerHTML = '';
    for (const f of files) {
      const li = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = f.name;
      const size = document.createElement('span');
      size.textContent = `${(f.size / 1048576).toFixed(1)} MB`;
      li.append(name, size);
      $('list').append(li);
    }
    $('go').disabled = files.length < 8;
    say(files.length < 8 ? `Please choose at least 8 photos (${files.length} selected).` : '');
  });

  async function api(body) {
    const res = await fetch('/api/upload-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order, token, ...body }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    return data;
  }

  $('go').addEventListener('click', async () => {
    $('go').disabled = true;
    $('files').disabled = true;
    try {
      let done = 0;
      for (let i = 0; i < files.length; i += 12) {
        const batch = files.slice(i, i + 12);
        const { uploads } = await api({ files: batch.map((f) => ({ name: f.name, size: f.size, type: f.type || 'image/jpeg' })) });
        for (const [j, u] of uploads.entries()) {
          const form = new FormData();
          form.append('cacheControl', '3600');
          form.append('', batch[j]);
          const res = await fetch(u.url, { method: 'PUT', body: form, headers: { 'x-upsert': 'false', ...(cfg.supabaseAnonKey ? { apikey: cfg.supabaseAnonKey } : {}) } });
          if (!res.ok) throw new Error(`Could not upload ${batch[j].name}`);
          done++;
          say(`Uploaded ${done} of ${files.length}…`);
        }
      }
      await api({ action: 'complete' });
      say('Thank you — your photos are in. We will email your film as soon as it is ready.');
    } catch (e) {
      say(e.message);
      $('go').disabled = false;
      $('files').disabled = false;
    }
  });
})();
