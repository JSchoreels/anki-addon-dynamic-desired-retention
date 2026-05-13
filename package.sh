#!/usr/bin/env bash
set -euo pipefail

addon_package="dynamic_desired_retention"
output_dir="dist"
output_file="${output_dir}/${addon_package}.ankiaddon"

mkdir -p "${output_dir}"
rm -f "${output_file}"

zip -r "${output_file}" \
  manifest.json \
  __init__.py \
  config.json \
  config.schema.json \
  config.md \
  README.md \
  docs \
  dynamic_desired_retention \
  -x '*/__pycache__/*' \
  -x '*.pyc' \
  -x '.pytest_cache/*'

python3 scripts/validate_ankiaddon.py "${output_file}"

echo "Created ${output_file}"
