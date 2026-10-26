select s.company,s.source_id from {{ ref('stg_financial') }} s
where (s.invoice_id is not null and not exists(select 1 from {{ ref('stg_financial') }} p where p.company=case when s.kind='intercompany_acceptance' then s.counterparty_company else s.company end and p.kind='invoice' and p.source_id=s.invoice_id))
or (s.payment_id is not null and not exists(select 1 from {{ ref('stg_financial') }} p where p.company=s.company and p.kind='payment' and p.source_id=s.payment_id))
union all
select company,invoice_id from {{ ref('intercompany_eliminations') }} where elimination_minor<>0 and (charge_count<>1 or acceptance_count<>1 or not content_matches)
