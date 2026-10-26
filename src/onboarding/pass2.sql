CREATE TABLE reviews(id uuid PRIMARY KEY,company text NOT NULL REFERENCES companies,kind text NOT NULL,
 actor text NOT NULL,reason text NOT NULL,context_hash text NOT NULL,payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE review_decisions(review_id uuid PRIMARY KEY REFERENCES reviews,company text NOT NULL REFERENCES companies,
 actor text NOT NULL,result text NOT NULL CHECK(result IN('approved','rejected')),reason text NOT NULL,
 decided_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE quarantine_resolutions(quarantine_id bigint PRIMARY KEY REFERENCES quarantine,
 company text NOT NULL REFERENCES companies,review_id uuid REFERENCES reviews,kind text NOT NULL,
 actor text NOT NULL,reason text NOT NULL,source_message_id bigint NOT NULL REFERENCES messages,
 detail jsonb NOT NULL,resolved_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE source_record_history(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,
 message_id bigint NOT NULL REFERENCES messages,body jsonb NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp());
INSERT INTO source_record_history(company,message_id,body) SELECT company,message_id,to_jsonb(source_records) FROM source_records;
CREATE FUNCTION capture_source_version() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
 INSERT INTO source_record_history(company,message_id,body) VALUES(NEW.company,NEW.message_id,to_jsonb(NEW)); RETURN NEW; END $$;
CREATE TRIGGER source_version AFTER INSERT OR UPDATE ON source_records FOR EACH ROW EXECUTE FUNCTION capture_source_version();
CREATE TABLE business_events(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,
 source text NOT NULL,event_id text NOT NULL,payload jsonb NOT NULL,hash text NOT NULL,status text NOT NULL,reason text NOT NULL,
 UNIQUE(company,source,event_id),observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE business_heads(company text NOT NULL REFERENCES companies,kind text NOT NULL,record_id text NOT NULL,
 canonical uuid NOT NULL,revision integer NOT NULL,event_id bigint NOT NULL REFERENCES business_events,
 payload jsonb NOT NULL,hash text NOT NULL,PRIMARY KEY(company,kind,record_id));
CREATE TABLE outbound(effect_id uuid PRIMARY KEY,company text NOT NULL REFERENCES companies,payload jsonb NOT NULL,hash text NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','uncertain','confirmed','exhausted','blocked')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),proof jsonb,detail text NOT NULL DEFAULT '',
 next_at timestamptz NOT NULL DEFAULT clock_timestamp(),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE outbound_attempts(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,effect_id uuid NOT NULL REFERENCES outbound,
 ordinal integer NOT NULL,stage text NOT NULL,result text NOT NULL,observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE FUNCTION frozen_outbound() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF ROW(NEW.effect_id,NEW.company,NEW.payload,NEW.hash,NEW.created_at) IS DISTINCT FROM ROW(OLD.effect_id,OLD.company,OLD.payload,OLD.hash,OLD.created_at)
 THEN RAISE EXCEPTION 'immutable_outbound_intent'; END IF; RETURN NEW; END $$;
CREATE TRIGGER outbound_intent BEFORE UPDATE ON outbound FOR EACH ROW EXECUTE FUNCTION frozen_outbound();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['reviews','review_decisions','quarantine_resolutions','source_record_history','business_events','outbound_attempts'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION immutable()',t);
 END LOOP;
END $$;
