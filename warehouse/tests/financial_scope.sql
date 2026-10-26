select s.company,s.source_id from {{ ref('stg_financial') }} s join {{ ref('dim_reporting_entities') }} d using(company)
where s.currency<>'USD' or s.legal_entity<>d.legal_entity or s.mapping_version<>d.mapping_version
union all
select a.company,a.allocation_id from {{ ref('fct_allocations') }} a join {{ ref('fct_invoices') }} i using(company,invoice_id) where a.currency<>i.currency
