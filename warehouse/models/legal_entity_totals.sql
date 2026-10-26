with periods as (
 select jsonb_array_elements_text(p.body->'periods')::date as period,p.body->>'currency' as currency
 from public.financial_policies p join public.financial_snapshots s on s.policy_version=p.version where s.id='{{ var("report_id") }}'
), base as (
select d.company,d.legal_entity,p.period,p.currency,
 coalesce((select sum(s.amount_minor) from {{ ref('stg_financial') }} s where s.company=d.company and s.period=p.period and s.kind='booking' and s.eligible),0)::bigint as bookings_minor,
 coalesce((select sum(i.gross_minor) from {{ ref('fct_invoices') }} i where i.company=d.company and i.period=p.period),0)::bigint as gross_invoice_minor,
 coalesce((select sum(i.credits_minor) from {{ ref('fct_invoices') }} i where i.company=d.company and i.period=p.period),0)::bigint as credits_minor,
 coalesce((select sum(i.net_minor) from {{ ref('fct_invoices') }} i where i.company=d.company and i.period=p.period),0)::bigint as net_invoice_minor,
 coalesce((select sum(s.amount_minor) from {{ ref('stg_financial') }} s join {{ ref('fct_invoices') }} i on i.company=s.company and i.invoice_id=s.invoice_id
 where s.company=d.company and s.period=p.period and s.kind='erp_posting' and s.eligible),0)::bigint as erp_posted_minor,
 coalesce((select sum(a.amount_minor) from {{ ref('fct_allocations') }} a where a.company=d.company and a.period=p.period),0)::bigint as allocated_cash_minor,
 coalesce((select sum(x.elimination_minor) from {{ ref('intercompany_eliminations') }} x where x.company=d.company and x.period=p.period),0)::bigint as elimination_minor
from {{ ref('dim_reporting_entities') }} d cross join periods p
)
select *, (net_invoice_minor-elimination_minor)::bigint as consolidated_invoice_minor,
 (erp_posted_minor-elimination_minor)::bigint as consolidated_erp_minor from base
