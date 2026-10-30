import crud
from database import SessionLocal


def send_directly(chat_id, sender, text):
    """WebSocket ke bina, seedha database mein message daalo (tez aur simple)."""
    with SessionLocal() as db:
        user = crud.find_user(db, sender)
        return crud.save_message(db, chat_id, user.id, text)


# ---------- Basic ----------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Guftagu" in r.text


# ---------- Signup / Login ----------
def test_signup_returns_token(client):
    r = client.post("/api/signup", json={"username": "jai", "password": "secret123"})
    assert r.status_code == 201
    assert r.json()["username"] == "jai"
    assert r.json()["token"]


def test_duplicate_username_rejected_case_insensitive(client):
    client.post("/api/signup", json={"username": "Jai", "password": "secret123"})
    r = client.post("/api/signup", json={"username": "jai", "password": "secret123"})
    assert r.status_code == 400


def test_signup_validation(client):
    short_name = client.post("/api/signup", json={"username": "ab", "password": "secret123"})
    bad_chars = client.post("/api/signup", json={"username": "jai kumar!", "password": "secret123"})
    short_pw = client.post("/api/signup", json={"username": "jai", "password": "123"})
    assert short_name.status_code == 422
    assert bad_chars.status_code == 422
    assert short_pw.status_code == 422


def test_login_success_and_failure(client, make_user):
    make_user("jai", "secret123")
    ok = client.post("/api/login", json={"username": "jai", "password": "secret123"})
    wrong = client.post("/api/login", json={"username": "jai", "password": "wrong-pass"})
    nobody = client.post("/api/login", json={"username": "nobody", "password": "secret123"})
    assert ok.status_code == 200 and ok.json()["token"]
    assert wrong.status_code == 401
    assert nobody.status_code == 401


def test_protected_routes_need_login(client):
    assert client.get("/api/chats").status_code == 401
    assert client.get("/api/users/search?q=a").status_code == 401
    r = client.get("/api/chats", headers={"Authorization": "Bearer fake-token"})
    assert r.status_code == 401


# ---------- Search ----------
def test_search_users(client, make_user):
    jai = make_user("jai")
    make_user("amit")
    make_user("rahul")
    r = client.get("/api/users/search?q=am", headers=jai["headers"])
    assert r.json() == ["amit"]
    r = client.get("/api/users/search?q=a", headers=jai["headers"])
    assert sorted(r.json()) == ["amit", "rahul"]  # jai khud list mein nahi
    assert client.get("/api/users/search?q=", headers=jai["headers"]).json() == []


# ---------- Private chat ----------
def test_start_private_chat_is_reused(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    first = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"])
    again = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"])
    reverse = client.post("/api/chats", json={"username": "jai"}, headers=amit["headers"])
    assert first.status_code == 200
    assert first.json()["name"] == "amit"
    assert first.json()["is_group"] is False
    # Dono taraf se ek hi chat, naya duplicate nahi
    assert first.json()["id"] == again.json()["id"] == reverse.json()["id"]


def test_cannot_chat_with_yourself_or_unknown_user(client, make_user):
    jai = make_user("jai")
    assert client.post("/api/chats", json={"username": "jai"}, headers=jai["headers"]).status_code == 400
    assert client.post("/api/chats", json={"username": "nobody"}, headers=jai["headers"]).status_code == 404


def test_chat_appears_in_both_lists_with_right_names(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"])
    jai_chats = client.get("/api/chats", headers=jai["headers"]).json()
    amit_chats = client.get("/api/chats", headers=amit["headers"]).json()
    assert [c["name"] for c in jai_chats] == ["amit"]
    assert [c["name"] for c in amit_chats] == ["jai"]


# ---------- Messages, unread, ticks ----------
def test_unread_count_and_mark_read(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"]).json()["id"]

    send_directly(chat_id, "jai", "hello")
    send_directly(chat_id, "jai", "kaise ho")

    assert client.get("/api/chats", headers=amit["headers"]).json()[0]["unread"] == 2
    assert client.get("/api/chats", headers=jai["headers"]).json()[0]["unread"] == 0  # apne messages unread nahi

    msgs = client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"]).json()
    assert [m["text"] for m in msgs] == ["hello", "kaise ho"]  # purane se naye order mein
    assert client.get("/api/chats", headers=amit["headers"]).json()[0]["unread"] == 0  # chat kholi = padh li


def test_message_status_progresses_to_read(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"]).json()["id"]
    send_directly(chat_id, "jai", "hi")

    before = client.get(f"/api/chats/{chat_id}/messages", headers=jai["headers"]).json()
    assert before[0]["status"] == "sent"

    client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"])  # amit ne padh li

    after = client.get(f"/api/chats/{chat_id}/messages", headers=jai["headers"]).json()
    assert after[0]["status"] == "read"
    # Doosre ke message par 'status' nahi aata
    amit_view = client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"]).json()
    assert "status" not in amit_view[0]


def test_non_member_cannot_read_chat(client, make_user):
    jai = make_user("jai")
    make_user("amit")
    rahul = make_user("rahul")
    chat_id = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"]).json()["id"]
    send_directly(chat_id, "jai", "secret baat")
    assert client.get(f"/api/chats/{chat_id}/messages", headers=rahul["headers"]).status_code == 404
    assert client.get("/api/chats/9999/messages", headers=rahul["headers"]).status_code == 404


def test_non_member_cannot_send_message(client, make_user):
    jai = make_user("jai")
    make_user("amit")
    make_user("rahul")
    chat_id = client.post("/api/chats", json={"username": "amit"}, headers=jai["headers"]).json()["id"]
    assert send_directly(chat_id, "rahul", "ghus gaya") is None


# ---------- Groups ----------
def test_create_group(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    make_user("rahul")
    r = client.post("/api/groups", json={"name": "Goa Trip", "members": ["amit", "rahul"]}, headers=jai["headers"])
    assert r.status_code == 201
    group = r.json()
    assert group["is_group"] is True
    assert group["name"] == "Goa Trip"
    assert sorted(group["members"]) == ["amit", "jai", "rahul"]  # banane wala bhi member
    amit_chats = client.get("/api/chats", headers=amit["headers"]).json()
    assert [c["name"] for c in amit_chats] == ["Goa Trip"]


def test_group_ignores_duplicates_unknown_and_self(client, make_user):
    jai = make_user("jai")
    make_user("amit")
    r = client.post(
        "/api/groups",
        json={"name": "Test", "members": ["jai", "amit", "amit", "nobody"]},
        headers=jai["headers"],
    )
    assert r.status_code == 201
    assert sorted(r.json()["members"]) == ["amit", "jai"]


def test_group_validation(client, make_user):
    jai = make_user("jai")
    make_user("amit")
    only_unknown = client.post("/api/groups", json={"name": "G", "members": ["nobody"]}, headers=jai["headers"])
    blank_name = client.post("/api/groups", json={"name": "   ", "members": ["amit"]}, headers=jai["headers"])
    no_members = client.post("/api/groups", json={"name": "G", "members": []}, headers=jai["headers"])
    assert only_unknown.status_code == 400
    assert blank_name.status_code == 400
    assert no_members.status_code == 422


def test_group_message_reaches_everyone_and_read_needs_all(client, make_user):
    jai = make_user("jai")
    amit = make_user("amit")
    rahul = make_user("rahul")
    gid = client.post("/api/groups", json={"name": "Goa", "members": ["amit", "rahul"]}, headers=jai["headers"]).json()["id"]

    result = send_directly(gid, "jai", "kab nikalna hai?")
    assert sorted(result["recipients"]) == ["amit", "jai", "rahul"]

    client.get(f"/api/chats/{gid}/messages", headers=amit["headers"])  # sirf amit ne padha
    status = client.get(f"/api/chats/{gid}/messages", headers=jai["headers"]).json()[0]["status"]
    assert status != "read"  # rahul ne abhi nahi padha

    client.get(f"/api/chats/{gid}/messages", headers=rahul["headers"])  # ab rahul ne bhi
    status = client.get(f"/api/chats/{gid}/messages", headers=jai["headers"]).json()[0]["status"]
    assert status == "read"  # sabne padh liya