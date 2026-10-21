import pytest
from scripts.backup_helpers import select_backup_root


def test_duplicate_backups_require_identical_inventory_and_content():
    summary = {"name": "node", "files": [{"path": "summary.txt", "size": 3}]}
    root = {
        "name": "node",
        "inventory": [["summary.txt", 3]],
        "fingerprint": "same",
        "path": "one",
    }
    duplicate = {**root, "path": "two"}
    assert select_backup_root([root, duplicate], summary) == root
    with pytest.raises(ValueError, match="differ in content"):
        select_backup_root([root, {**duplicate, "fingerprint": "different"}], summary)
    with pytest.raises(ValueError, match="complete file inventory"):
        select_backup_root([{**root, "inventory": [["other.txt", 3]]}], summary)
    assert (
        select_backup_root(
            [{**root, "inventory": [["summary.txt", 4]]}, duplicate], summary
        )
        == duplicate
    )
