# Packaging Data

`package.sh` creates `dist/dynamic_desired_retention.ankiaddon`.

The script reads the add-on source files from the repository root and writes a
fresh package archive. If an older archive exists at the same path, it is
deleted before the new archive is created.

The generated archive is ignored by git because it is build output.
