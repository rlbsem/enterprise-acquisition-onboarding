"""Separate deterministic portfolio.v1; never modifies the original/annual fixtures."""

import copy
from dataclasses import dataclass
from psycopg.types.json import Jsonb
from .fixtures import mapping, canonical, documents, approve_mapping
from .contracts import digest
from .db import connect

PERIODS = ["2026-01-01", "2026-10-01"]
ORIGINAL = "2026-11-02T00:00:00+00:00"
RESTATED = "2026-11-05T00:00:00+00:00"


def company_id(index):
    # Alphabetic IDs also work with the existing console username contract.
    return "acq-" + "".join(chr(97 + (index // divisor) % 26) for divisor in [676, 26, 1])


@dataclass
class Portfolio:
    count: int = 50

    def __post_init__(self):
        if type(self.count) is not int or not 3 <= self.count <= 100:
            raise ValueError("portfolio_requires_3_to_100_companies")
        dates = ["2025-10-01", "2026-02-01", "2026-06-01", "2026-01-01", "2026-08-01", "2027-01-01"]
        self.companies = [
            (
                company_id(i),
                f"Synthetic {['Field Services', 'Facilities', 'Maintenance'][i % 3]} {i + 1:03}",
                f"SYN-LE-{i + 1:04}",
                dates[i % 6],
                ["hubspot", "salesforce", "legacy"][i % 3],
            )
            for i in range(self.count)
        ]

    def mode(self, index):
        if index % 11 == 9:
            return "identity_held"
        if index % 13 == 10:
            return "coverage_held"
        if index % 17 == 13:
            return "pending_review"
        return "ready"

    def version(self, index):
        return 2 if index % 7 == 5 else 1

    def contract(self, index):
        result = mapping(self.companies[index][4])
        if self.version(index) == 2:
            rule = next(r for r in result["sources"].values() if r["domain"] == "finance")
            old = next(iter(rule["fields"]))
            rule["fields"]["reviewedControlState"] = rule["fields"].pop(old)
            rule["states"]["reviewedControlState"] = rule["states"].pop(old)
        return result

    def customer_count(self, index):
        return 2 + index % 3

    def messages(self, index):
        company, _, entity, _, style = self.companies[index]
        result = []
        for number in range(self.customer_count(index)):
            for message in documents(company, style, entity):
                rule = mapping(style)["sources"][message["source"]]
                message["data"][rule["id"]] = str(100 + number)
                message["event_id"] = f"customer-{100 + number}-{rule['domain']}-v1"
                message["mapping_version"] = self.version(index)
                if self.version(index) == 2 and rule["domain"] == "finance":
                    old = next(iter(rule["fields"]))
                    message["data"]["reviewedControlState"] = message["data"].pop(old)
                result.append(message)
        return result

    def seed(self, dsn):
        # Trusted disposable-fixture reset, matching the original installer's lifecycle.
        with connect(dsn) as c:
            c.execute(
                "TRUNCATE audit,gate_runs,customer_fields,source_records,quarantine,deliveries,messages,baselines,crosswalks,customers,mapping_versions,systems,companies,platforms RESTART IDENTITY CASCADE"
            )
            c.execute(
                "INSERT INTO platforms VALUES('synthetic-portfolio','Synthetic acquisition portfolio')"
            )
            for company, name, entity, acquired, style in self.companies:
                c.execute(
                    "INSERT INTO companies(id,parent,name,legal_entity,acquired_on) VALUES(%s,'synthetic-portfolio',%s,%s,%s)",
                    (company, name, entity, acquired),
                )
                for source, rule in mapping(style)["sources"].items():
                    c.execute(
                        "INSERT INTO systems VALUES(%s,%s,%s,%s)",
                        (company, source, rule["domain"], source + "-account-contract.v1"),
                    )
        messages = []
        for i, (company, _, entity, _, style) in enumerate(self.companies):
            approve_mapping(
                dsn,
                company,
                1,
                mapping(style),
                "synthetic-installer",
                "portfolio.v1-reviewed-source-contract",
            )
            if self.version(i) == 2:
                approve_mapping(
                    dsn,
                    company,
                    2,
                    self.contract(i),
                    "synthetic-installer",
                    "portfolio.v1-reviewed-finance-field-change",
                )
            incoming = self.messages(i)
            with connect(dsn) as c:
                for j in range(self.customer_count(i)):
                    c.execute(
                        "INSERT INTO customers VALUES(%s,%s,%s,%s)",
                        (company, entity, canonical(company, j + 1), "Common Property Group"),
                    )
                    for source, rule in self.contract(i)["sources"].items():
                        if not (
                            self.mode(i) == "identity_held"
                            and rule["domain"] == "operations"
                            and j == 0
                        ):
                            c.execute(
                                "INSERT INTO crosswalks VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                (
                                    company,
                                    entity,
                                    source,
                                    str(100 + j),
                                    canonical(company, j + 1),
                                    self.version(i),
                                    "synthetic-reviewed-company-and-entity-match",
                                ),
                            )
                for source, rule in self.contract(i)["sources"].items():
                    expected = {
                        m["data"][rule["id"]]: {"revision": 1, "hash": digest(m["data"])}
                        for m in incoming
                        if m["source"] == source
                    }
                    c.execute(
                        "INSERT INTO baselines VALUES(%s,%s,%s,%s,%s)",
                        (
                            company,
                            source,
                            self.version(i),
                            Jsonb(expected),
                            "portfolio.v1-independent-source-manifest",
                        ),
                    )
            messages.extend(incoming)
        return messages

    def expected_admitted(self, index, recovered=False):
        return self.mode(index) == "ready" and (index != 1) and (index != 0 or recovered)

    def financial(self):
        rows = []

        def add(i, kind, key, amount, day, customer="100", **refs):
            company, _, entity, _, _ = self.companies[i]
            domain = "crm" if kind == "booking" else "finance"
            source = next(
                s for s, r in self.contract(i)["sources"].items() if r["domain"] == domain
            )
            rows.append(
                dict(
                    schema_version="financial-fact.v1",
                    company=company,
                    legal_entity=entity,
                    source=source,
                    owner=domain,
                    source_customer_id=customer,
                    event_id=f"{kind}:{key}:1",
                    kind=kind,
                    source_id=key,
                    revision=1,
                    mapping_version=self.version(i),
                    currency="USD",
                    amount_minor=amount,
                    transaction_date=day,
                    observed_at="2026-11-01T12:00:00+00:00",
                    **refs,
                )
            )

        for i in range(self.count):
            for j in range(self.customer_count(i)):
                customer = str(100 + j)
                for month in [1, 10]:
                    key = f"{customer}-{month:02}"
                    gross = 3_000_000 + i * 91_000 + j * 37_000 + month * 11_000
                    credit = gross // (50 + i % 4)
                    net = gross - credit
                    cash = net * (55 + i % 20) // 100
                    day = f"2026-{month:02}-10"
                    add(i, "booking", "B-" + key, gross * (2 + i % 3), day, customer)
                    add(i, "invoice", "I-" + key, gross, day, customer, booking_id="B-" + key)
                    for line, amount in [(1, gross * 3 // 5), (2, gross - gross * 3 // 5)]:
                        add(
                            i,
                            "invoice_line",
                            f"L{line}-" + key,
                            amount,
                            day,
                            customer,
                            invoice_id="I-" + key,
                        )
                    add(i, "credit", "CR-" + key, credit, day, customer, invoice_id="I-" + key)
                    add(
                        i,
                        "erp_posting",
                        "P-" + key,
                        gross - (12_500 if i % 7 == 2 else 0),
                        day,
                        customer,
                        invoice_id="I-" + key,
                    )
                    add(
                        i, "erp_posting", "PC-" + key, -credit, day, customer, invoice_id="I-" + key
                    )
                    add(i, "payment", "PAY-" + key, cash + 2_500, day, customer)
                    add(
                        i,
                        "allocation",
                        "A-" + key,
                        cash,
                        day,
                        customer,
                        invoice_id="I-" + key,
                        payment_id="PAY-" + key,
                    )
        for i in range(2, self.count - 1, 5):
            other = self.companies[i + 1]
            issuer = self.companies[i]
            refs = dict(counterparty_company=other[0], counterparty_entity=other[2])
            amount = 250_000 + i * 1_000
            add(i, "invoice", "IC1", amount, "2026-10-15", **refs)
            add(i, "invoice_line", "IC1-L1", amount, "2026-10-15", invoice_id="IC1")
            add(i, "erp_posting", "PIC1", amount, "2026-10-15", invoice_id="IC1")
            add(
                i,
                "intercompany_charge",
                "CH1",
                amount,
                "2026-10-15",
                invoice_id="IC1",
                link_id="shared-service",
                **refs,
            )
            if i % 2 == 0:
                add(
                    i + 1,
                    "intercompany_acceptance",
                    "AC1",
                    amount,
                    "2026-10-15",
                    invoice_id="IC1",
                    link_id="shared-service",
                    counterparty_company=issuer[0],
                    counterparty_entity=issuer[2],
                )
        from .finance import Financial

        return [Financial.model_validate(row).model_dump() for row in rows]

    def corrections(self):
        # Correct an October contract across its header, line and ERP grain. Keep its posting variance.
        index = 2
        source = self.companies[index][0]
        rows = [
            copy.deepcopy(r)
            for r in self.financial()
            if r["company"] == source and r["source_id"] in ["I-100-10", "L1-100-10", "P-100-10"]
        ]
        for r in rows:
            r.update(
                revision=2,
                event_id=r["event_id"][:-1] + "2",
                amount_minor=r["amount_minor"] + 137_000,
                observed_at="2026-11-04T12:00:00+00:00",
            )
        return rows

    def policy(self, accepted):
        inventory = {c[0]: {} for c in self.companies}
        for row in accepted:
            inventory[row["company"]].setdefault(row["kind"], []).append(row["source_id"])
        return dict(
            schema_version="portfolio-financial-policy.v1",
            currency="USD",
            periods=PERIODS,
            perimeter={
                c: dict(legal_entity=e, acquired_on=d, reporting_unit=c)
                for c, _, e, d, _ in self.companies
            },
            inventory=inventory,
            elimination="one_exact_charge_and_independent_counterparty_acceptance.v1",
            basis="document_and_allocation_dates; no_preacquisition_carryforward; no_recognized_revenue",
            actor="synthetic-finance-reviewer",
            reason="Reviewed separate portfolio.v1 source manifest; incomplete source inventory blocks publication.",
            scenario=dict(
                id="multi-company-v1", company_count=self.count, profiles={}, synthetic=True
            ),
        )
