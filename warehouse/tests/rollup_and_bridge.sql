select period::text as source_id from {{ ref('portfolio_totals') }}
where consolidated_invoice_minor<>net_invoice_minor-elimination_minor or consolidated_erp_minor<>erp_posted_minor-elimination_minor
union all select period::text from {{ ref('restatement_bridge') }} where after_minor-before_minor<>delta_minor
