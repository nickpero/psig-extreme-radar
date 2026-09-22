from scanner.psig_catalyst import _classify


def test_catalyst_classification():
    assert _classify("F-3", "Registration Statement") == "FINANCING"
    assert _classify("6-K", "Current Report") == "SEC_6K"
    assert _classify("4", "Statement of changes in beneficial ownership") == "OWNERSHIP"


def test_sec_403_is_non_fatal_and_logs_warning(monkeypatch, caplog):
    import requests
    from scanner.psig_catalyst import recent_filings

    response = requests.Response()
    response.status_code = 403
    response.url = "https://data.sec.gov/submissions/CIK0001997201.json"

    monkeypatch.setattr(
        "scanner.psig_catalyst.requests.get",
        lambda *args, **kwargs: response,
    )

    with caplog.at_level("WARNING"):
        assert recent_filings() == []

    assert "HTTP 403" in caplog.text
    assert "will retry next cycle" in caplog.text


def test_sec_timeout_is_non_fatal_and_logs_warning(monkeypatch, caplog):
    import requests
    from scanner.psig_catalyst import recent_filings

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("SEC timeout")

    monkeypatch.setattr("scanner.psig_catalyst.requests.get", raise_timeout)

    with caplog.at_level("WARNING"):
        assert recent_filings() == []

    assert "SEC catalyst monitor request failed" in caplog.text
    assert "will retry next cycle" in caplog.text
