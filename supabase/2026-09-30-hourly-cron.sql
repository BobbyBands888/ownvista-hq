-- Backup hourly trigger for the agents (GitHub's own schedule skipped 3 hours on Sep 30).
-- Supabase pg_cron calls GitHub's "run workflow" API at :37 every hour. The router runs each
-- hourly agent at most once per hour, so a double trigger never double-runs an agent.
-- Needs the Vault secret "github_dispatch_token" (fine-grained token: this repo, Actions read & write).
create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.unschedule(jobid) from cron.job where jobname = 'ownvista-hq-hourly';

select cron.schedule('ownvista-hq-hourly', '37 * * * *', $job$
  select net.http_post(
    url := 'https://api.github.com/repos/BobbyBands888/ownvista-hq/actions/workflows/hq.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token' limit 1),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'ownvista-hq-cron',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('agent', 'auto'))
  );
$job$);

select jobid, jobname, schedule, active from cron.job where jobname = 'ownvista-hq-hourly';
