import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_integration import API, ask, upload


@pytest.mark.skipif(
    os.environ.get("TEST_NATIVE_POSTGRES") != "1", reason="Requires native PostgreSQL transaction isolation"
)
def test_parallel_submission_creates_one_ticket(clients):
    student, admin, _ = clients
    upload(admin)
    conv, _ = ask(student)
    draft = student.post(API + f"/conversations/{conv}/ticket-draft").json()
    body = {key: draft[key] for key in ("title", "category", "description")}
    body["draft_id"] = draft["id"]

    def submit(_):
        response = student.post(API + "/tickets", json=body, headers={"Idempotency-Key": "parallel-submit"})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(submit, range(4)))
    assert len(set(ids)) == 1
    assert student.get(API + "/tickets").json()["total"] == 1
