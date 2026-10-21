"""Resolve bundle roots without guessing between different collected contents."""


def select_backup_root(roots, summary):
    expected = {file["path"]: file["size"] for file in summary["files"]}
    matches = [
        root
        for root in roots
        if root["name"] == summary["name"] and dict(root["inventory"]) == expected
    ]
    if not matches:
        raise ValueError(
            "No bundle root matches the complete file inventory; upgrade must stop"
        )
    if len(matches) > 1 and len({root["fingerprint"] for root in matches}) != 1:
        raise ValueError(
            "Bundle roots share file names/sizes but differ in content; upgrade must stop"
        )
    # Byte-identical copies are interchangeable; retain separate records in the manifest.
    return matches[0]
