with documents as (select * from {{ ref('stg_financial') }} where eligible),
 child as (
 select company,invoice_id,
 coalesce(sum(amount_minor) filter(where kind='invoice_line'),0)::bigint as lines_minor,
 coalesce(sum(amount_minor) filter(where kind='credit'),0)::bigint as credits_minor,
 coalesce(sum(amount_minor) filter(where kind='erp_posting'),0)::bigint as erp_minor,
 count(*) filter(where kind='erp_posting')::integer as erp_count
 from documents where invoice_id is not null and kind in('invoice_line','credit','erp_posting') group by company,invoice_id
)
select i.company,i.legal_entity,i.source_id as invoice_id,i.period,i.currency,i.amount_minor as gross_minor,
 coalesce(c.lines_minor,0)::bigint as lines_minor, coalesce(c.credits_minor,0)::bigint as credits_minor,
 (i.amount_minor-coalesce(c.credits_minor,0))::bigint as net_minor,
 coalesce(c.erp_minor,0)::bigint as erp_minor,coalesce(c.erp_count,0)::integer as erp_count,
 array(select d.event_id from documents d where d.company=i.company and
 (d.event_id=i.event_id or (d.invoice_id=i.source_id and d.kind in('invoice_line','credit','erp_posting'))) order by d.event_id) as source_event_ids
from documents i left join child c on c.company=i.company and c.invoice_id=i.source_id where i.kind='invoice'
