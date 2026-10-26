select company,invoice_id as source_id from {{ ref('fct_invoices') }} i
where gross_minor<>lines_minor or net_minor<0 or credits_minor<0 or
coalesce((select sum(a.amount_minor) from {{ ref('fct_allocations') }} a where a.company=i.company and a.invoice_id=i.invoice_id),0)>net_minor
union all
select p.company,p.source_id from {{ ref('stg_financial') }} p where p.kind='payment' and p.eligible and
coalesce((select sum(a.amount_minor) from {{ ref('fct_allocations') }} a where a.company=p.company and a.payment_id=p.source_id),0)>p.amount_minor
