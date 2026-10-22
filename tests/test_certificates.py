from datetime import datetime, timedelta, timezone
import json
import pytest
from backend.catalog import IndexedBundle
from backend.certificates import certificate_page, parse_certificates, reference_time
from conftest import upload, make_archive

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)


def certificate(
    before=NOW - timedelta(days=1), after=NOW + timedelta(days=365), ca=False
):
    return f"""Certificate:
    Data:
        Serial Number: 123
        Issuer: CN = example-ca
        Validity
            Not Before: {before.strftime('%b %d %H:%M:%S %Y GMT')}
            Not After : {after.strftime('%b %d %H:%M:%S %Y GMT')}
        Subject: CN = service
        X509v3 extensions:
            X509v3 Basic Constraints:
                CA:{'TRUE' if ca else 'FALSE'}
            X509v3 Extended Key Usage:
                TLS Web Server Authentication
            X509v3 Subject Alternative Name:
                DNS:example.test, IP Address:127.0.0.1
"""


def bundle(tmp_path, files):
    root = tmp_path / "files"
    root.mkdir()
    for name, text in {
        "summary.txt": "Hostname: fixture-node\nDistro: rke2\nGenerated: Wed Oct 21 16:21:06 CST 2026\n",
        **files,
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return IndexedBundle(root, tmp_path / "index.sqlite")


def test_validity_boundaries_and_pagination(tmp_path):
    b = bundle(
        tmp_path,
        {
            "rke2/certs/server/expired.crt": certificate(after=NOW),
            "rke2/certs/server/soon.crt": certificate(after=NOW + timedelta(days=90)),
            "rke2/certs/server/valid.crt": certificate(
                after=NOW + timedelta(days=90, seconds=1)
            ),
            "rke2/certs/server/future.crt": certificate(
                before=NOW + timedelta(seconds=1)
            ),
            "rke2/certs/server/ca.crt": certificate(ca=True),
            "rke2/certs/server/damaged.crt": "broken",
            "rke2/certs/server/pem.crt": "-----BEGIN CERTIFICATE-----\n...\n",
            "rke2/certs/server/oversize.crt": "x" * (1024 * 1024 + 1),
            "rke2/certs/server/secret.key": "private: must not parse",
        },
    )
    first = certificate_page(b, limit=2, now=NOW)
    assert first["counts"] == {
        "valid": 2,
        "expiring": 1,
        "expired": 1,
        "notYetValid": 1,
        "unknown": 3,
    }
    assert [r["validity"] for r in first["items"]] == ["expired", "expiring"]
    second = certificate_page(
        b, limit=2, cursor=first["nextCursor"], now=NOW + timedelta(days=999)
    )
    assert (
        second["checkedAt"] == first["checkedAt"]
    )  # stable time within one pagination session
    assert second["total"] == 8
    with pytest.raises(ValueError, match="游标"):
        certificate_page(b, limit=2, cursor=first["nextCursor"], q="changed")
    ca = certificate_page(b, purpose="ca", now=NOW)
    assert ca["total"] == 1 and ca["items"][0]["isCA"] is True
    assert certificate_page(b, status="unknown", now=NOW)["total"] == 3
    assert certificate_page(b, q="service", now=NOW)["total"] == 5
    assert (
        certificate_page(b, q="oversize", now=NOW)["items"][0]["parseState"]
        == "oversize"
    )


def test_multi_certificate_and_invalid_dates():
    records = parse_certificates(certificate() + certificate(ca=True))
    assert len(records) == 2 and records[1]["purpose"] == "ca"
    assert records[0]["san"] == "DNS:example.test, IP Address:127.0.0.1"
    assert (
        parse_certificates(certificate().replace("Not After", "Missing"))[0][
            "parseState"
        ]
        == "invalid"
    )
    assert (
        parse_certificates(certificate(before=NOW + timedelta(days=500)))[0][
            "parseState"
        ]
        == "invalid"
    )


def test_collection_time_does_not_guess_cst(tmp_path):
    b = bundle(tmp_path, {"rke2/certs/server/test.crt": certificate()})
    result = certificate_page(b, basis="collected", now=NOW)
    assert result["referenceTime"] is None and result["counts"]["unknown"] == 1
    assert "CST" in result["referenceMessage"]
    assert certificate_page(b, basis="collected", zone="Asia/Shanghai", now=NOW)[
        "referenceTime"
    ].startswith("2026-10-21T08:21:06")
    with pytest.raises(ValueError, match="时区"):
        certificate_page(b, zone="invalid-zone")
    b.header["generated"] = "2026-10-21T16:21:06+08:00"
    assert reference_time(b, "collected", "", NOW)[0].hour == 8
    b.header["generated"] = "Wed Oct 21 16:21:06 GMT 2026"
    assert reference_time(b, "collected", "", NOW)[0].hour == 16
    b.header["generated"] = "Wed Oct 21 16:21:06 +0800 2026"
    assert reference_time(b, "collected", "", NOW)[0].hour == 8
    b.header["generated"] = "Sun Nov 01 01:30:00 CDT 2026"
    with pytest.raises(ValueError, match="夏令时"):
        reference_time(b, "collected", "America/Chicago", NOW)
    b.header["generated"] = "nonsense"
    assert reference_time(b, "collected", "", NOW)[0] is None


def test_certificate_api_validation_and_sources(client):
    record = upload(
        client,
        make_archive(
            {
                "summary.txt": "Hostname: test\nDistro: rke2\n",
                "rke2/certs/server/multi.crt": certificate() + certificate(ca=True),
            }
        ),
    )
    base = "/api/v1/bundles/" + record["id"]
    response = client.get(base + "/certificates")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2 and {r["sourceIndex"] for r in items} == {1, 2}
    assert all(r["node"] == "test" and r["source"].endswith("multi.crt") for r in items)
    for query in (
        "limit=201",
        "status=invalid",
        "basis=bad",
        "purpose=bad",
        "zone=bad",
    ):
        assert client.get(base + "/certificates?" + query).status_code in (400, 422)


def test_explicit_package_timezone_and_paged_certificate_inventory(tmp_path):
    b = bundle(
        tmp_path,
        {
            "rke2/certs/server/multi.crt": certificate() * 51,
            "systeminfo/timedatectl": "Time zone: Asia/Shanghai (CST, +0800)",
            "rke2/certs/server/binary.crt": "\x00binary",
        },
    )
    result = certificate_page(b, basis="collected", now=NOW)
    assert result["referenceTime"].startswith("2026-10-21T08:21:06")
    assert result["total"] == 52 and len(result["items"]) == 50
    second = certificate_page(
        b, basis="collected", now=NOW, cursor=result["nextCursor"]
    )
    assert len(second["items"]) == 2
    assert len({r["id"] for r in result["items"] + second["items"]}) == 52
    binary = certificate_page(b, q="binary", now=NOW)["items"][0]
    assert binary["parseState"] == "unsupported"
