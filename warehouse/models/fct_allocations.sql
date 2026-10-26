select a.company,a.legal_entity,a.source_id as allocation_id,a.invoice_id,a.payment_id,a.period,a.currency,a.amount_minor,
 array[a.event_id,p.event_id,i.event_id] as source_event_ids
from {{ ref('stg_financial') }} a
join {{ ref('stg_financial') }} p on p.company=a.company and p.kind='payment' and p.source_id=a.payment_id and p.eligible
join {{ ref('stg_financial') }} i on i.company=a.company and i.kind='invoice' and i.source_id=a.invoice_id and i.eligible
where a.kind='allocation' and a.eligible
