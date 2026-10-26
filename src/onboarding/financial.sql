CREATE TABLE financial_events(id bigserial PRIMARY KEY, company text NOT NULL REFERENCES companies,
 source text NOT NULL, event_id text NOT NULL, body jsonb NOT NULL, hash text NOT NULL,
 status text NOT NULL CHECK(status IN('accepted','rejected')), reason text NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(company,source,event_id));
CREATE TABLE financial_policies(version integer PRIMARY KEY, body jsonb NOT NULL, hash text NOT NULL,
 actor text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE financial_snapshots(id text PRIMARY KEY, policy_version integer NOT NULL REFERENCES financial_policies,
 cutoff timestamptz NOT NULL, previous_id text REFERENCES financial_snapshots, control jsonb NOT NULL,
 input_hash text NOT NULL, capture_txid bigint NOT NULL DEFAULT txid_current(),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE financial_inputs(report_id text NOT NULL REFERENCES financial_snapshots, event_id bigint NOT NULL REFERENCES financial_events,
 body jsonb NOT NULL, hash text NOT NULL, PRIMARY KEY(report_id,event_id));
CREATE TABLE financial_publications(report_id text PRIMARY KEY REFERENCES financial_snapshots,
 results jsonb NOT NULL, comparisons jsonb NOT NULL, bridge jsonb NOT NULL,
 published_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE FUNCTION closed_financial_inputs() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM financial_snapshots WHERE id=NEW.report_id AND capture_txid=txid_current())
 THEN RAISE EXCEPTION 'financial_snapshot_closed'; END IF; RETURN NEW; END $$;
CREATE TRIGGER closed_snapshot BEFORE INSERT ON financial_inputs FOR EACH ROW EXECUTE FUNCTION closed_financial_inputs();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['financial_events','financial_policies','financial_snapshots','financial_inputs','financial_publications'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION immutable()',t);
 END LOOP;
END $$;
