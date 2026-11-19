#!/usr/bin/env bash
set -euo pipefail
image="$1"
report_dir="$2"
mkdir -p "$report_dir"
scanner_dir=$(mktemp -d)
trap 'rm -rf "$scanner_dir"' EXIT
curl --fail --location --retry 3 --output "$scanner_dir/trivy.tar.gz" https://github.com/aquasecurity/trivy/releases/download/v0.76.2/trivy_0.76.2_Linux-64bit.tar.gz
echo "bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf  $scanner_dir/trivy.tar.gz" | sha256sum --check
tar -xzf "$scanner_dir/trivy.tar.gz" -C "$scanner_dir" trivy
"$scanner_dir/trivy" image --image-src docker --scanners vuln,secret --pkg-types os,library --list-all-pkgs --ignore-unfixed=false --timeout 15m --format json --output "$report_dir/trivy.json" "$image"
"$scanner_dir/trivy" --version > "$report_dir/scanner-version.txt"
docker image inspect "$image" > "$report_dir/image-inspect.json"
python - "$report_dir" <<'PY'
import collections,json,sys
from pathlib import Path
root=Path(sys.argv[1]);report=json.loads((root/'trivy.json').read_text())
rows=[];blocked=[]
for result in report.get('Results',[]):
    vulnerabilities=result.get('Vulnerabilities',[])
    rows.append({'class':result.get('Class'),'type':result.get('Type'),'packages':len(result.get('Packages',[])),'severities':dict(collections.Counter(v['Severity'] for v in vulnerabilities)),'with_fix':sum(bool(v.get('FixedVersion')) for v in vulnerabilities),'secrets':len(result.get('Secrets',[]))})
    for v in vulnerabilities:
        if v.get('FixedVersion') and (v['Severity'] in ('HIGH','CRITICAL') or result.get('Class')=='lang-pkgs'):
            blocked.append({'package':v['PkgName'],'id':v['VulnerabilityID'],'severity':v['Severity'],'fixed':v['FixedVersion']})
    if result.get('Secrets'):blocked.append({'issue':'embedded_secret_detected','count':len(result['Secrets'])})
summary={'os':report.get('Metadata',{}).get('OS'),'results':rows,'publication_blockers':blocked}
(root/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
if blocked:raise SystemExit('Image publication blocked: fixable high/critical OS findings, fixable language findings or embedded secrets')
PY
