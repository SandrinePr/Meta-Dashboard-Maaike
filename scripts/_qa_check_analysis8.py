import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)
from maaike.db import connect

conn = connect(Path(os.environ["MAAIKE_DATABASE_PATH"]))
row = conn.execute(
    "SELECT id, status, input_snapshot_json FROM post_ai_analyses WHERE id=8"
).fetchone()
snap = json.loads(row["input_snapshot_json"])
exe = snap.get("executable") or {}
images = exe.get("images_for_model") or []
print(
    json.dumps(
        {
            "status": row["status"],
            "image_count": len(images),
            "roles": [i.get("role") for i in images],
            "paths": [i.get("path") for i in images],
            "estimate": snap.get("cost_estimate_usd"),
            "system_chars": len(exe.get("system_text") or ""),
            "user_chars": len(exe.get("user_text") or ""),
        },
        indent=2,
    )
)
# types matrix
matrix = Path("data/imports/redrock/_qa_prepare_types_matrix.json")
if matrix.exists():
    data = json.loads(matrix.read_text(encoding="utf-8"))
    summary = {
        k: {
            "post_id": v.get("post_id"),
            "analysis_id": v.get("analysis_id"),
            "coverage": v.get("coverage"),
            "images_for_model": v.get("images_for_model"),
            "image_roles": v.get("image_roles"),
            "full_video_to_model": v.get("full_video_to_model"),
            "audio_to_model": v.get("audio_to_model"),
            "estimate": v.get("cost_estimate_usd"),
        }
        for k, v in (data.get("posts") or {}).items()
    }
    summary["stories"] = data.get("stories")
    print("MATRIX", json.dumps(summary, indent=2, ensure_ascii=False)[:3000])
conn.close()
