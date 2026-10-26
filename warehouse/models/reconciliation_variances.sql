select company,legal_entity,period,invoice_id as source_id,
 case when erp_count=0 then 'erp_posting_missing' else 'erp_posting_difference' end as code,
 (net_minor-erp_minor)::bigint as amount_minor from {{ ref('fct_invoices') }} where net_minor<>erp_minor or erp_count=0
union all
select company,legal_entity,period,invoice_id,'invoice_line_difference',(gross_minor-lines_minor)::bigint
from {{ ref('fct_invoices') }} where gross_minor<>lines_minor
union all
select company,legal_entity,period,invoice_id,'intercompany_unresolved',net_minor
from {{ ref('intercompany_eliminations') }} where elimination_minor=0
union all
select p.company,p.legal_entity,p.period,p.source_id,'unallocated_payment',
 (p.amount_minor-coalesce(a.amount_minor,0))::bigint
from {{ ref('stg_financial') }} p left join
(select company,payment_id,sum(amount_minor)::bigint as amount_minor from {{ ref('fct_allocations') }} group by company,payment_id) a
on a.company=p.company and a.payment_id=p.source_id
where p.kind='payment' and p.eligible and p.amount_minor<>coalesce(a.amount_minor,0)
