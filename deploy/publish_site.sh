#!/bin/zsh
# Build the public scoreboard page and upload it to $SITE_S3 (e.g. s3://bucket/peashooter), both as the bare key
# (so /peashooter works behind CloudFront) and as <key>/index.html (so /peashooter/ does too). Caches for 5 minutes.
# Settings come from the crontab: SITE_S3, AWS_PROFILE, and optionally UV and AWS (paths to uv and the AWS CLI).
set -euo pipefail
cd "${0:A:h}/.."
: "${SITE_S3:?set SITE_S3, e.g. s3://your-bucket/peashooter}"
"${UV:-uv}" run --extra nba admin.py --no-sync site
for key in "${SITE_S3%/}" "${SITE_S3%/}/index.html"; do
  "${AWS:-aws}" s3 cp data/site/index.html "$key" --only-show-errors \
    --content-type "text/html; charset=utf-8" --cache-control "max-age=300"
done
echo "Published to ${SITE_S3%/}"
