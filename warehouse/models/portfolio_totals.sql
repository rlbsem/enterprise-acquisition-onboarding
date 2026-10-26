select period,currency,
sum(bookings_minor)::bigint as bookings_minor,
sum(gross_invoice_minor)::bigint as gross_invoice_minor,
sum(credits_minor)::bigint as credits_minor,
sum(net_invoice_minor)::bigint as net_invoice_minor,
sum(erp_posted_minor)::bigint as erp_posted_minor,
sum(allocated_cash_minor)::bigint as allocated_cash_minor,
sum(elimination_minor)::bigint as elimination_minor,
sum(consolidated_invoice_minor)::bigint as consolidated_invoice_minor,
sum(consolidated_erp_minor)::bigint as consolidated_erp_minor
from {{ ref('legal_entity_totals') }} group by period,currency
