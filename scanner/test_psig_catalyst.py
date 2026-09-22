from scanner.psig_catalyst import _classify


def test_catalyst_classification():
    assert _classify("F-3", "Registration Statement") == "FINANCING"
    assert _classify("6-K", "Current Report") == "SEC_6K"
    assert _classify("4", "Statement of changes in beneficial ownership") == "OWNERSHIP"
