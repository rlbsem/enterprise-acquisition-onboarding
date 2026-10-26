with parsed as (
 select i.event_id, i.hash, i.body, i.body->>'company' as company, i.body->>'legal_entity' as legal_entity,
 i.body->>'source' as source, i.body->>'kind' as kind, i.body->>'source_id' as source_id,
 i.body->>'currency' as currency, (i.body->>'amount_minor')::bigint as amount_minor,
 (i.body->>'transaction_date')::date as transaction_date,
 date_trunc('month',(i.body->>'transaction_date')::date)::date as period,
 i.body->>'invoice_id' as invoice_id, i.body->>'payment_id' as payment_id,
 i.body->>'counterparty_company' as counterparty_company,
 i.body->>'counterparty_entity' as counterparty_entity, i.body->>'link_id' as link_id,
 (i.body->>'mapping_version')::integer as mapping_version, s.policy_version,
 coalesce((select body->'periods' from public.financial_policies where version=s.policy_version),'[]'::jsonb) as periods
 from public.financial_inputs i join public.financial_snapshots s on s.id=i.report_id
 where i.report_id='{{ var("report_id") }}'
), scoped as (
select p.*, d.admitted and p.transaction_date>=d.acquired_on and p.periods ? p.period::text as eligible,
 case when not d.admitted then 'admission_held' when p.transaction_date<d.acquired_on then 'pre_acquisition'
 when not(p.periods ? p.period::text) then 'outside_period' else 'included' end as inclusion_reason
from parsed p join {{ ref('dim_reporting_entities') }} d using(company)
)
select s.event_id,s.hash,s.body,s.company,s.legal_entity,s.source,s.kind,s.source_id,s.currency,s.amount_minor,
 s.transaction_date,s.period,s.invoice_id,s.payment_id,s.counterparty_company,s.counterparty_entity,s.link_id,s.mapping_version,
 s.eligible and (s.invoice_id is null or exists(select 1 from scoped p where p.company=case when s.kind='intercompany_acceptance' then s.counterparty_company else s.company end and p.kind='invoice' and p.source_id=s.invoice_id and p.eligible))
 and (s.payment_id is null or exists(select 1 from scoped p where p.company=s.company and p.kind='payment' and p.source_id=s.payment_id and p.eligible)) as eligible,
 case when not s.eligible then s.inclusion_reason
 when s.invoice_id is not null and not exists(select 1 from scoped p where p.company=case when s.kind='intercompany_acceptance' then s.counterparty_company else s.company end and p.kind='invoice' and p.source_id=s.invoice_id and p.eligible) then 'parent_outside_perimeter'
 when s.payment_id is not null and not exists(select 1 from scoped p where p.company=s.company and p.kind='payment' and p.source_id=s.payment_id and p.eligible) then 'parent_outside_perimeter'
 else 'included' end as inclusion_reason
from scoped s
