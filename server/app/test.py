# test_glossary.py (run from project root)

import uuid

from app.core.database import SyncSessionLocal
from app.services.brief_generator import generate_brief

REPO_ID: uuid.UUID = uuid.UUID("1c67f65b-7a60-476e-932a-b34f139a3ce4")


def main():
    print("Starting brief generation test...")
    with SyncSessionLocal() as db:
        guide = generate_brief(db, REPO_ID)
        print(f"Done. Narrative: {(guide.architecture_brief or {}).get('narrative', '')}")

main()
