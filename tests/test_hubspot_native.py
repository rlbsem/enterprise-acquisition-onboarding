"""Offline provider-contract tests: no HubSpot calls or real Service Keys."""

import copy

import httpx
import pytest

from onboarding.hubspot_native import (
    CedarFixture,
    HubSpotBoundaryError,
    HubSpotReadOnlyReader,
    main,
)

PAIR = CedarFixture()
SAMPLE_KEY = "unit-test-never-a-real-token"


def provider_records():
    company = {
        "id": PAIR.company_id,
        "archived": False,
        "properties": {"name": PAIR.company_name},
        "associations": {
            "contacts": {"results": [{"id": PAIR.contact_id, "type": "company_to_contact"}]}
        },
    }
    contact = {
        "id": PAIR.contact_id,
        "archived": False,
        "properties": {
            "firstname": PAIR.firstname,
            "lastname": PAIR.lastname,
            "email": PAIR.email,
        },
        "associations": {
            "companies": {"results": [{"id": PAIR.company_id, "type": "contact_to_company"}]}
        },
    }
    return company, contact


def fake_transport(company=None, contact=None, status=200, calls=None):
    base_company, base_contact = provider_records()
    company = base_company if company is None else company
    contact = base_contact if contact is None else contact
    calls = [] if calls is None else calls

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.hubapi.com"
        assert request.url.scheme == "https"
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {SAMPLE_KEY}"
        if request.url.path == f"/crm/objects/2026-09/companies/{PAIR.company_id}":
            assert request.url.params["properties"] == "name"
            assert request.url.params["associations"] == "contacts"
            return httpx.Response(status, json=company)
        if request.url.path == f"/crm/objects/2026-09/contacts/{PAIR.contact_id}":
            assert request.url.params["properties"] == "firstname,lastname,email"
            assert request.url.params["associations"] == "companies"
            return httpx.Response(status, json=contact)
        raise AssertionError("unexpected_provider_target")

    return httpx.MockTransport(handler), calls


def test_read_only_api_exact_records_bidirectional_association_and_replay():
    transport, calls = fake_transport()
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        first = reader.verify()
        second = reader.verify()
    assert len(calls) == 4
    assert {c.method for c in calls} == {"GET"}
    assert first["sanitized_projection_sha256"] == second["sanitized_projection_sha256"]
    assert first["checks"] == {
        "company_object": "matched",
        "contact_object": "matched",
        "contact_to_company": "matched",
        "company_to_contact": "matched",
    }
    assert first["crm_writes"] == 0
    assert first["verified_portal_id_by_api"] is False
    assert first["acquisition_admission_executed"] is False
    assert first["cdc_continuity_verified"] is False
    assert SAMPLE_KEY not in str(first)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (("company", "id", "other"), "source_identity_or_shape_mismatch"),
        (("contact", "id", "other"), "source_identity_or_shape_mismatch"),
        (("company", "archived", True), "source_identity_or_shape_mismatch"),
        (("contact", "archived", True), "source_identity_or_shape_mismatch"),
        (("company", "name", "Unexpected services"), "company_name_diverged"),
        (("contact", "email", "wrong@example.com"), "contact_field_diverged"),
        (("contact", "lastname", "Other"), "contact_field_diverged"),
        (("company", "association", []), "company_contact_link_diverged"),
        (("contact", "association", []), "contact_company_link_diverged"),
        (("company", "association", [{"id": "999"}]), "company_contact_link_diverged"),
        (("contact", "association", [{"id": "999"}]), "contact_company_link_diverged"),
        (
            ("company", "association", [{"id": PAIR.contact_id}, {"id": PAIR.contact_id}]),
            "duplicate_association",
        ),
        (("contact", "paging", {"next": {"after": "x"}}), "association_page_incomplete"),
    ],
)
def test_source_mismatch_or_ambiguous_link_fails_closed(mutation, expected_reason):
    company, contact = copy.deepcopy(provider_records())
    target, field, value = mutation
    record = company if target == "company" else contact
    if field in {"name", "email", "lastname"}:
        record["properties"][field] = value
    elif field == "association":
        record["associations"]["contacts" if target == "company" else "companies"]["results"] = (
            value
        )
    elif field == "paging":
        record["associations"]["contacts" if target == "company" else "companies"][field] = value
    else:
        record[field] = value
    transport, calls = fake_transport(company, contact)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        with pytest.raises(HubSpotBoundaryError, match=expected_reason):
            reader.verify()
    assert calls and all(request.method == "GET" for request in calls)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "service_key_access_denied"),
        (403, "service_key_access_denied"),
        (404, "source_record_not_found"),
        (429, "provider_rate_limited_no_replay"),
        (503, "provider_unexpected_status"),
        (302, "provider_unexpected_status"),
    ],
)
def test_status_codes_are_bounded_and_not_silently_retried(status, reason):
    transport, calls = fake_transport(status=status)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        with pytest.raises(HubSpotBoundaryError, match=reason):
            reader.verify()
    assert len(calls) == 1


def test_broken_provider_json_and_transport_never_leak_secrets():
    def invalid(_request):
        return httpx.Response(200, text="not-json " + SAMPLE_KEY)

    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=httpx.MockTransport(invalid)) as reader:
        with pytest.raises(HubSpotBoundaryError) as err:
            reader.verify()
    assert str(err.value) == "provider_invalid_json"
    assert SAMPLE_KEY not in str(err.value)

    def offline(request):
        raise httpx.ConnectTimeout("simulated provider timeout", request=request)

    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=httpx.MockTransport(offline)) as reader:
        with pytest.raises(HubSpotBoundaryError) as err:
            reader.verify()
    assert str(err.value) == "provider_transport_unavailable"


def test_missing_credential_and_cli_gate_do_not_call_hubspot(monkeypatch, capsys):
    monkeypatch.delenv("HUBSPOT_SERVICE_KEY", raising=False)
    with pytest.raises(HubSpotBoundaryError, match="service_key_not_configured"):
        HubSpotReadOnlyReader("")
    assert main(["--read-only"]) == 2
    assert "service_key_not_configured" in capsys.readouterr().out
    with pytest.raises(SystemExit) as err:
        main([])
    assert err.value.code == 2


def test_primary_and_unlabeled_types_for_one_company_are_one_identity():
    company, contact = provider_records()
    contact["associations"]["companies"]["results"].append(
        {"id": PAIR.company_id, "type": "contact_to_company_unlabeled"}
    )
    transport, calls = fake_transport(company, contact)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        assert reader.verify()["checks"]["contact_to_company"] == "matched"
    assert len(calls) == 2


def test_typed_extra_company_remains_rejected():
    company, contact = provider_records()
    contact["associations"]["companies"]["results"] = [
        {"id": "other-company", "type": "contact_to_company"},
        {"id": PAIR.company_id, "type": "contact_to_company_unlabeled"},
        {"id": "other-company", "type": "contact_to_company_unlabeled"},
    ]
    transport, _ = fake_transport(company, contact)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        with pytest.raises(HubSpotBoundaryError, match="contact_company_link_diverged"):
            reader.verify()


@pytest.mark.parametrize("label", [None, "contact_to_company"])
def test_repeated_exact_association_pair_is_not_silently_deduplicated(label):
    company, contact = provider_records()
    row = {"id": PAIR.company_id, "type": label}
    contact["associations"]["companies"]["results"] = [row, copy.deepcopy(row)]
    transport, _ = fake_transport(company, contact)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        with pytest.raises(HubSpotBoundaryError, match="duplicate_association"):
            reader.verify()


@pytest.mark.parametrize("label", [[], ""])
def test_invalid_association_type_fails_closed(label):
    company, contact = provider_records()
    contact["associations"]["companies"]["results"][0]["type"] = label
    transport, _ = fake_transport(company, contact)
    with HubSpotReadOnlyReader(SAMPLE_KEY, transport=transport) as reader:
        with pytest.raises(HubSpotBoundaryError, match="association_schema_invalid"):
            reader.verify()
