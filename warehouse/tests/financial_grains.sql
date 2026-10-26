select company,invoice_id from {{ ref('fct_invoices') }} group by company,invoice_id having count(*)<>1
union all select company,allocation_id from {{ ref('fct_allocations') }} group by company,allocation_id having count(*)<>1
union all select company,invoice_id from {{ ref('intercompany_eliminations') }} group by company,invoice_id having count(*)<>1
union all select company,source_id from {{ ref('stg_financial') }} group by company,kind,source_id having count(*)<>1
