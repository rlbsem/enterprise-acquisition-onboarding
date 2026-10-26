with links as (
 select i.company,i.legal_entity,i.invoice_id,i.period,i.net_minor,
 count(distinct c.event_id)::integer as charge_count,count(distinct a.event_id)::integer as acceptance_count,
 coalesce(bool_and(c.amount_minor=i.net_minor and a.amount_minor=i.net_minor and a.currency=i.currency
 and c.currency=i.currency and a.counterparty_entity=i.legal_entity),false) as content_matches,
 array_agg(distinct c.event_id order by c.event_id) filter(where c.event_id is not null) as charge_event_ids,
 array_agg(distinct a.event_id order by a.event_id) filter(where a.event_id is not null) as acceptance_event_ids
 from {{ ref('fct_invoices') }} i
 join {{ ref('stg_financial') }} h on h.company=i.company and h.kind='invoice' and h.source_id=i.invoice_id
 left join {{ ref('stg_financial') }} c on c.company=i.company and c.kind='intercompany_charge' and c.invoice_id=i.invoice_id
 and c.counterparty_company=h.counterparty_company and c.counterparty_entity=h.counterparty_entity and c.eligible
 left join {{ ref('stg_financial') }} a on a.company=h.counterparty_company and a.kind='intercompany_acceptance'
 and a.invoice_id=i.invoice_id and a.counterparty_company=i.company and a.counterparty_entity=i.legal_entity and a.link_id=c.link_id and a.eligible
 where h.counterparty_company is not null
 group by i.company,i.legal_entity,i.invoice_id,i.period,i.net_minor
)
select l.*,case when l.charge_count=1 and l.acceptance_count=1 and l.content_matches and i.erp_minor=i.net_minor
 and not exists(select 1 from {{ ref('fct_allocations') }} a where a.company=l.company and a.invoice_id=l.invoice_id)
 then l.net_minor else 0 end::bigint as elimination_minor
from links l join {{ ref('fct_invoices') }} i using(company,legal_entity,invoice_id,period)
