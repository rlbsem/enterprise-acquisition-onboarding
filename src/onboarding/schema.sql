CREATE TABLE platforms(id text PRIMARY KEY,name text NOT NULL);
CREATE TABLE companies(id text PRIMARY KEY,parent text NOT NULL REFERENCES platforms,
 name text NOT NULL,legal_entity text NOT NULL,acquired_on date NOT NULL,
 status text NOT NULL DEFAULT 'registered' CHECK(status IN('registered','staged','held','portfolio_ready')),
 active_mapping integer,gate_hash text,UNIQUE(id,legal_entity));
CREATE TABLE systems(company text REFERENCES companies,source text NOT NULL,domain text NOT NULL,
 contract_name text NOT NULL,PRIMARY KEY(company,source),UNIQUE(company,domain));
CREATE TABLE mapping_versions(company text REFERENCES companies,version integer NOT NULL CHECK(version>0),
 body jsonb NOT NULL,hash text NOT NULL,reviewed_by text NOT NULL,review_reference text NOT NULL,
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(company,version));
CREATE TABLE customers(company text NOT NULL,legal_entity text NOT NULL,id uuid NOT NULL,name text NOT NULL,
 PRIMARY KEY(company,id),FOREIGN KEY(company,legal_entity) REFERENCES companies(id,legal_entity));
CREATE TABLE crosswalks(company text NOT NULL,legal_entity text NOT NULL,source text NOT NULL,source_id text NOT NULL,
 canonical uuid NOT NULL,version integer NOT NULL,proof text NOT NULL,
 PRIMARY KEY(company,source,source_id,version),UNIQUE(company,source,canonical,version),FOREIGN KEY(company,legal_entity) REFERENCES companies(id,legal_entity),
 FOREIGN KEY(company,canonical) REFERENCES customers(company,id),FOREIGN KEY(company,version) REFERENCES mapping_versions);
CREATE TABLE baselines(company text NOT NULL,source text NOT NULL,version integer NOT NULL,
 expected jsonb NOT NULL,review_reference text NOT NULL,PRIMARY KEY(company,source,version),
 FOREIGN KEY(company,source) REFERENCES systems,FOREIGN KEY(company,version) REFERENCES mapping_versions);
CREATE TABLE messages(id bigserial PRIMARY KEY,company text NOT NULL,source text NOT NULL,event_id text NOT NULL,
 body jsonb NOT NULL,hash text NOT NULL,status text NOT NULL DEFAULT 'received',
 reason text NOT NULL DEFAULT '',created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(company,source,event_id),FOREIGN KEY(company,source) REFERENCES systems);
CREATE TABLE deliveries(id bigserial PRIMARY KEY,message_id bigint REFERENCES messages,company text NOT NULL,
 source text NOT NULL,event_id text NOT NULL,incoming jsonb NOT NULL,hash text NOT NULL,
 outcome text NOT NULL,observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE quarantine(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,
 message_id bigint REFERENCES messages,reason text NOT NULL,detail jsonb NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE source_records(company text NOT NULL,source text NOT NULL,source_id text NOT NULL,
 canonical uuid NOT NULL,revision integer NOT NULL,version integer NOT NULL,message_id bigint NOT NULL REFERENCES messages,
 raw jsonb NOT NULL,raw_hash text NOT NULL,normalized jsonb NOT NULL,observed_at timestamptz NOT NULL,
 PRIMARY KEY(company,source,source_id),FOREIGN KEY(company,canonical) REFERENCES customers(company,id));
CREATE TABLE customer_fields(company text NOT NULL,canonical uuid NOT NULL,field text NOT NULL,value jsonb NOT NULL,
 source text NOT NULL,source_id text NOT NULL,revision integer NOT NULL,message_id bigint NOT NULL REFERENCES messages,
 PRIMARY KEY(company,canonical,field),FOREIGN KEY(company,canonical) REFERENCES customers(company,id));
CREATE TABLE gate_runs(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,input_hash text NOT NULL,
 result jsonb NOT NULL,observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE audit(id bigserial PRIMARY KEY,company text NOT NULL REFERENCES companies,action text NOT NULL,
 reference text NOT NULL,detail jsonb NOT NULL,observed_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE FUNCTION immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable_evidence'; END $$;
CREATE FUNCTION frozen_message() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF ROW(NEW.company,NEW.source,NEW.event_id,NEW.body,NEW.hash,NEW.created_at) IS DISTINCT FROM
 ROW(OLD.company,OLD.source,OLD.event_id,OLD.body,OLD.hash,OLD.created_at) OR OLD.status<>'received'
 THEN RAISE EXCEPTION 'immutable_message'; END IF; RETURN NEW; END $$;
CREATE TRIGGER frozen_message BEFORE UPDATE ON messages FOR EACH ROW EXECUTE FUNCTION frozen_message();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['mapping_versions','baselines','crosswalks','deliveries','quarantine','gate_runs','audit'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION immutable()',t);
 END LOOP;
END $$;
