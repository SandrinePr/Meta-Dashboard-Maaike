"""Restore Meta display names and probe Claude without printing secrets."""

from __future__ import annotations

from maaike.claude_analysis import claude_connection_status, probe_claude_connection
from maaike.db import connect


def main() -> None:
    conn = connect()
    conn.execute(
        """
        UPDATE clients
        SET meta_page_name = ?,
            meta_ig_username = ?
        WHERE id = 1 AND meta_status = 'revoked'
        """,
        ("Red Rock Agency", "redrock.agency"),
    )
    row = conn.execute("SELECT meta_status_detail FROM clients WHERE id = 1").fetchone()
    detail = (row[0] if row else "") or ""
    if "redrock.agency" not in detail.lower():
        detail = (detail + " Laatst gekoppeld: Red Rock Agency (@redrock.agency).").strip()
        conn.execute("UPDATE clients SET meta_status_detail = ? WHERE id = 1", (detail,))
    conn.commit()
    print("restored_display_names")

    status = claude_connection_status()
    print(
        "claude_status",
        {
            k: status[k]
            for k in ("configured", "key_variable", "key_source", "missing_setting", "model")
        },
    )
    probe = probe_claude_connection()
    print("claude_probe", {k: probe[k] for k in probe})


if __name__ == "__main__":
    main()
