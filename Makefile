PY ?= python3
DB ?= out/gtm.db
NOW ?=
NOWFLAG = $(if $(NOW),--now $(NOW),)

.PHONY: test pipeline route plays digest daily health demo clean

test:            ## run unit + integration tests
	GTM_LLM_MOCK=1 $(PY) -m unittest discover -s tests -v

pipeline:        ## ingest -> dedupe -> score -> CRM write-back (GTM_CRM=dryrun|hubspot|salesforce)
	$(PY) skills/account-data-pipeline/scripts/run_pipeline.py --db $(DB) $(NOWFLAG)

route:           ## route inbound leads
	$(PY) skills/inbound-routing/scripts/route_leads.py --db $(DB) $(NOWFLAG)

plays:           ## build signal-based outbound worklist (+ Claude drafts)
	$(PY) skills/signal-based-outbound/scripts/build_plays.py --db $(DB) --draft $(NOWFLAG)

digest:          ## print rep daily alerts (add SEND=1 to post to Slack)
	$(PY) skills/rep-daily-alerts/scripts/daily_digest.py $(if $(SEND),--send,)

daily: pipeline route plays digest   ## the morning run, in dependency order

health:          ## health check; exit 1 when red
	$(PY) skills/gtm-reliability-ops/scripts/health_check.py --db $(DB)

demo: clean      ## full offline demo on sample data
	$(MAKE) daily NOW=2026-11-25T12:00:00Z
	$(PY) skills/account-research-agent/scripts/research_account.py acme-analytics.com
	$(PY) skills/crm-update-agent/scripts/notes_to_crm.py examples/data/call_notes_acme.txt --current '{"stage":"discovery"}'
	$(PY) skills/proposal-generator/scripts/build_proposal.py --account "Acme Analytics" --plan growth --seats 18 \
	  --notes examples/data/call_notes_acme.txt --brief out/briefs/acme-analytics.com.md

clean:
	rm -rf out .locks
