"""Explicitly collect an approved company feed, then publish validated cached links."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    path = os.environ.get('NEWS_CLAW_TASK_CONFIG_PATH')
    if not args.execute:
        print(json.dumps({'success': True, 'business_status': 'preview', 'network_requests_made': 0}))
        return 0
    if not path:
        parser.error('Launch through the Go engine')
    task = json.loads(Path(path).read_text())
    review = task['collector'].get('access_review', {})
    if review.get('status') not in {'public_publisher_feed', 'public_regulator_api'} or review.get('authentication') != 'none_required':
        parser.error('An approved public feed or regulator API access review is required')
    limit = task['collector']['request_policy'].get('max_requests_per_run', 0)
    if not 1 <= limit <= 6:
        parser.error('An explicit request limit of 1 to 6 is required')
    result_path = Path(os.environ['NEWS_CLAW_RESULT_PATH'])
    collected = subprocess.run([sys.executable, '-m', 'collectors.news'], check=False)
    if collected.returncode:
        return collected.returncode
    collection = json.loads(result_path.read_text())
    # Keep the network audit even when a later local publication fails.
    (result_path.parent / 'collection-result.json').write_text(json.dumps(collection, indent=2))
    published = subprocess.run(['/mnt/quant/strategies/stocks-quant/web/.venv/bin/python',
        '-m', 'workflows.company_watch', '--publish-only', '--execute'], check=False)
    result = json.loads(result_path.read_text())
    result['collection'] = collection
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return published.returncode


if __name__ == '__main__':
    raise SystemExit(main())
