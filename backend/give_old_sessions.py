"""Give every session from before accounts (no owner yet) to one person, and move its files
into that person's folders. Run it once, after that person has signed up on the site:

    python -m backend.give_old_sessions you@example.com

On the server, inside the running container:

    docker exec courtiq python -m backend.give_old_sessions you@example.com
"""

import sys
from pathlib import Path

from . import app as api
from . import database


def give_old_sessions(email):
    """Returns how many sessions were handed over."""
    user = database.get_user_by_email(email.strip().lower())
    if user is None:
        raise SystemExit(f"No account for {email}. Sign up on the site first.")

    # One transaction: if moving a folder fails, no row changes owner. Folders already moved
    # are skipped on the next run, since only their new place exists then.
    with database.connect() as connection:
        sessions = connection.execute(
            "SELECT id, input_path, output_path FROM sessions WHERE user_id IS NULL FOR UPDATE"
        ).fetchall()
        for session in sessions:
            new_paths = {}
            for column, root in [("input_path", api.UPLOAD_ROOT), ("output_path", api.RESULT_ROOT)]:
                old_folder = root / session["id"]
                new_folder = api.session_folder(root, user["id"], session["id"])
                if old_folder.exists():
                    new_folder.parent.mkdir(parents=True, exist_ok=True)
                    old_folder.rename(new_folder)
                # A failed session has no output_path.
                old_path = session[column]
                new_paths[column] = (
                    str((new_folder / Path(old_path).name).relative_to(api.PROJECT_ROOT))
                    if old_path else None
                )
            connection.execute(
                "UPDATE sessions SET user_id = %s, input_path = %s, output_path = %s WHERE id = %s",
                (user["id"], new_paths["input_path"], new_paths["output_path"], session["id"]),
            )
        # The monthly stats are kept per person, so they need the new owners.
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")
    return len(sessions)


if __name__ == "__main__":
    email = sys.argv[1]
    print(f"Gave {give_old_sessions(email)} sessions to {email}.")
