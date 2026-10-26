select p.key as company, p.value->>'legal_entity' as legal_entity,
 (p.value->>'acquired_on')::date as acquired_on, p.value->>'reporting_unit' as reporting_unit,
 (p.value->>'admitted')::boolean as admitted, (p.value->>'mapping_version')::integer as mapping_version
from public.financial_snapshots s cross join lateral jsonb_each(s.control) p
where s.id = '{{ var("report_id") }}'
