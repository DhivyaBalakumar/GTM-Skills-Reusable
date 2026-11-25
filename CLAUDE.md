# Working in this repo

- Skills live in `skills/<name>/SKILL.md`; shared logic lives in `gtm_core/`. Put reusable logic in `gtm_core`, not in skill scripts.
- `gtm_core` stays **stdlib-only**. The `anthropic` package is imported lazily in `gtm_core/llm.py` only.
- Run `make test` before every commit. Any behaviour change (scoring, routing, dedupe, validation) needs a test in `tests/test_core.py`.
- `make demo` must keep working offline. Agents need a `mock=` fallback so they run without `ANTHROPIC_API_KEY`.
- Schema changes are additive. Update `sql/schema.sql`, every reader (`grep -r <column> gtm_core skills`) and `gtm-data-model/SKILL.md` together.
- Never send emails or messages automatically. Outreach is drafts only, and risky CRM fields (stage, amount, close_date) always go to human review.
- Keep weights, plays, territories and pricing in config files, not code.
- After adding or renaming a skill, run `python3 scripts/check_skills.py` (the `name` must match the folder).
