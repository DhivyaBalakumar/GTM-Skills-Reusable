# Postmortem: {{short title}}
**Date:** {{YYYY-MM-DD}} · **Severity:** {{1/2/3}} · **Author:** {{name}} · **Status:** draft / final

## Summary
{{2–3 sentences: what broke, who was affected, how long, current state.}}

## Impact
- Leads / accounts affected: {{n}}
- Reps affected: {{n / teams}}
- Business impact: {{e.g. 14 tier-A demo requests waited > 4 h instead of 5 min SLA}}

## Timeline (UTC)
| Time | Event |
|---|---|
| | first bad event |
| | detected (how: alert / rep report) |
| | mitigated |
| | fixed |

## Root cause
{{What actually caused it. Use the 5 whys; stop at the system/process cause.}}

## Why we didn't catch it sooner
{{missing test / missing monitor / alert went to wrong channel}}

## Resolution
- Fix: {{PR link}}
- Data repair: {{replay / backfill done, counts}}

## Action items
| Action | Type (prevent / detect / mitigate) | Owner | Due |
|---|---|---|---|
| | | | |

## Lessons
- What went well:
- What to improve:
