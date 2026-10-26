with old as (
 select x.value from public.financial_snapshots s join public.financial_publications p on p.report_id=s.previous_id
 cross join lateral jsonb_array_elements(p.results->'portfolio_totals') x where s.id='{{ var("report_id") }}'
)
select n.period,v.metric,(o.value->>v.metric)::bigint as before_minor,v.amount as after_minor,
 (v.amount-(o.value->>v.metric)::bigint)::bigint as delta_minor
from {{ ref('portfolio_totals') }} n join old o on (o.value->>'period')::date=n.period
cross join lateral(values
('bookings_minor',n.bookings_minor),
('gross_invoice_minor',n.gross_invoice_minor),
('credits_minor',n.credits_minor),
('net_invoice_minor',n.net_invoice_minor),
('erp_posted_minor',n.erp_posted_minor),
('allocated_cash_minor',n.allocated_cash_minor),
('elimination_minor',n.elimination_minor),
('consolidated_invoice_minor',n.consolidated_invoice_minor),
('consolidated_erp_minor',n.consolidated_erp_minor))v(metric,amount)
