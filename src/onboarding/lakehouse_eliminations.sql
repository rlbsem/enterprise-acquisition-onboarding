-- Exact bilateral evidence, including unmatched additional charge/acceptance rows.
WITH charge_counts AS (
    SELECT i.company, i.invoice_id, count(c.source_id) AS charge_count
    FROM {ns}.invoices i
    LEFT JOIN {ns}.eligible c
      ON c.company=i.company AND c.kind='intercompany_charge'
     AND c.invoice_id=i.invoice_id AND c.counterparty_company=i.counterparty_company
     AND c.counterparty_entity=i.counterparty_entity
    GROUP BY i.company, i.invoice_id
), acceptance_counts AS (
    SELECT i.company, i.invoice_id,
           count(DISTINCT a.source_id) AS acceptance_count,
           sum(CASE WHEN c.amount_minor=i.net_minor AND a.amount_minor=i.net_minor
                     AND c.currency=i.currency AND a.currency=i.currency
                    THEN 1 ELSE 0 END) AS exact_pairs
    FROM {ns}.invoices i
    LEFT JOIN {ns}.eligible c
      ON c.company=i.company AND c.kind='intercompany_charge'
     AND c.invoice_id=i.invoice_id AND c.counterparty_company=i.counterparty_company
     AND c.counterparty_entity=i.counterparty_entity
    LEFT JOIN {ns}.eligible a
      ON a.company=i.counterparty_company AND a.kind='intercompany_acceptance'
     AND a.invoice_id=i.invoice_id AND a.counterparty_company=i.company
     AND a.counterparty_entity=i.legal_entity AND a.link_id=c.link_id
    GROUP BY i.company, i.invoice_id
), cash_counts AS (
    SELECT company, invoice_id, count(*) AS allocations
    FROM {ns}.eligible WHERE kind='allocation' GROUP BY company, invoice_id
)
SELECT i.company, i.invoice_id, i.period, i.net_minor,
       CASE WHEN c.charge_count=1 AND a.acceptance_count=1 AND a.exact_pairs=1
                 AND i.erp_minor=i.net_minor AND coalesce(p.allocations,0)=0
            THEN i.net_minor ELSE 0 END AS elimination_minor
FROM {ns}.invoices i
JOIN charge_counts c ON c.company=i.company AND c.invoice_id=i.invoice_id
JOIN acceptance_counts a ON a.company=i.company AND a.invoice_id=i.invoice_id
LEFT JOIN cash_counts p ON p.company=i.company AND p.invoice_id=i.invoice_id
WHERE i.counterparty_company IS NOT NULL
