# Packaging Data

`package.sh` creates `dist/dynamic_desired_retention.ankiaddon`.

The script reads the add-on source files from the repository root and writes a
fresh package archive. If an older archive exists at the same path, it is
deleted before the new archive is created.

After creating the archive, the script runs `scripts/validate_ankiaddon.py`.
Validation reads the archive, checks that required runtime files such as
`dynamic_desired_retention/api.py` are present, and rejects cache/build files
that should not ship.

The generated archive is ignored by git because it is build output.
