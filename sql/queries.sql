-- Everyday GTM queries against the central data layer (SQLite dialect).

-- 1. Top accounts to work right now, with reasons
SELECT a.name, a.domain, a.owner_email, s.tier, s.score, s.reasons
FROM accounts a JOIN current_account_scores s USING(account_id)
ORDER BY s.score DESC LIMIT 25;

-- 2. Buying-committee gaps on tier A/B accounts (who to multithread to)
SELECT cc.name, cc.domain, s.tier,
       CASE WHEN cc.economic_buyers = 0 THEN 'economic_buyer ' ELSE '' END ||
       CASE WHEN cc.champions = 0 THEN 'champion ' ELSE '' END ||
       CASE WHEN cc.technical_evaluators = 0 THEN 'technical_evaluator' ELSE '' END AS missing_roles
FROM committee_coverage cc JOIN current_account_scores s USING(account_id)
WHERE s.tier IN ('A','B') AND (cc.economic_buyers = 0 OR cc.champions = 0 OR cc.technical_evaluators = 0);

-- 3. Hot but unowned (nothing high-intent should sit unassigned)
SELECT a.name, a.domain, s.score FROM accounts a JOIN current_account_scores s USING(account_id)
WHERE a.owner_email IS NULL AND s.tier IN ('A','B') ORDER BY s.score DESC;

-- 4. Score movers: accounts whose score jumped >= 20 points since the previous run
WITH ranked AS (
  SELECT account_id, score, scored_at,
         LAG(score) OVER (PARTITION BY account_id ORDER BY scored_at) AS prev
  FROM account_scores)
SELECT a.name, r.prev, r.score, r.scored_at FROM ranked r JOIN accounts a USING(account_id)
WHERE r.prev IS NOT NULL AND r.score - r.prev >= 20 ORDER BY r.scored_at DESC;

-- 5. Speed-to-lead: median minutes to first touch by tier (needs first_touch_at populated from CRM activity sync)
SELECT tier, COUNT(*) leads,
       AVG((julianday(first_touch_at) - julianday(created_at)) * 1440) AS avg_minutes_to_touch,
       SUM(CASE WHEN first_touch_at > sla_due_at OR first_touch_at IS NULL THEN 1 ELSE 0 END) AS sla_misses
FROM routing_assignments GROUP BY tier;

-- 6. Routing audit: which rule sends how many leads where
SELECT rule, assigned_to, COUNT(*) n FROM routing_assignments GROUP BY rule, assigned_to ORDER BY n DESC;

-- 7. Duplicate pressure: golden accounts built from 2+ source records
SELECT golden_key, COUNT(*) source_records, GROUP_CONCAT(source || ':' || source_id) lineage
FROM source_records WHERE entity_type = 'account' GROUP BY golden_key HAVING COUNT(*) > 1;

-- 8. Pipeline reliability: job success rate & duration, last 7 days
SELECT job_name, COUNT(*) runs,
       ROUND(100.0 * SUM(status = 'success') / COUNT(*), 1) AS success_pct,
       ROUND(AVG((julianday(finished_at) - julianday(started_at)) * 86400), 1) AS avg_seconds
FROM job_runs WHERE started_at >= datetime('now', '-7 days') GROUP BY job_name;

-- 9. Signals per type in the last 30 days (is a signal source going quiet = broken?)
SELECT type, COUNT(*) n, MAX(occurred_at) latest FROM signals
WHERE occurred_at >= datetime('now', '-30 days') GROUP BY type ORDER BY n DESC;
