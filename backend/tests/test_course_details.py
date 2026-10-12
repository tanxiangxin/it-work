from tests.test_campus_features import API, course, upload


def test_uploaded_document_details_are_private_paginated_and_invalid_after_delete(clients):
    student, admin, other = clients
    cid = course(student)
    data = upload(
        student, cid, "# 原子性\n\n数据库事务全部成功或全部失败。\n\n# 隔离性\n\n并发事务互不干扰。"
    )
    path = API + f"/courses/{cid}/documents/{data['document_id']}"
    result = student.get(path, params={"page_size": 1}).json()
    assert result["name"] and result["chunk_total"] >= 2 and len(result["chunks"]) == 1
    assert result["content_format"] == "markdown"
    assert result["chunks"][0]["heading"] == "原子性"
    assert "全部成功" in result["chunks"][0]["content"]
    next_page = student.get(path, params={"page_size": 1, "page": 2}).json()
    assert next_page["chunks"][0]["id"] != result["chunks"][0]["id"]
    assert next_page["chunks"][0]["heading"] == "隔离性"
    for client in [admin, other]:
        assert client.get(path).status_code == 404
    other_course = course(student, "其他课程")
    assert student.get(API + f"/courses/{other_course}/documents/{data['document_id']}").status_code == 404
    student.delete(path)
    assert student.get(path).status_code == 404
