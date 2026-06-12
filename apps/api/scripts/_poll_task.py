import json
import sys
import time
import urllib.request

task_id = int(sys.argv[1])
base = f"http://127.0.0.1:8000/api/collection-tasks/{task_id}"
for i in range(60):
    t = json.loads(urllib.request.urlopen(base, timeout=30).read())
    st = t["status"]
    ins = t.get("inserted_count") or 0
    tgt = t.get("discovery_limit") or 5
    print(
        f"[{i}] status={st} inserted={ins}/{tgt} "
        f"discovered={t.get('discovered_count')} filtered={t.get('filtered_out_count')}"
    )
    if st != "running":
        print("last_error:", (t.get("last_error") or "")[:500])
        print("summary:", (t.get("status_summary") or "")[:500])
        sys.exit(0 if ins >= tgt else 2)
    time.sleep(20)
print("timeout")
sys.exit(3)
