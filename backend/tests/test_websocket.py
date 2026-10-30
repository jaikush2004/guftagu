import pytest
from starlette.websockets import WebSocketDisconnect


def ws_url(user):
    return f"/ws?token={user['token']}"


def make_chat(client, a, b):
    r = client.post("/api/chats", json={"username": b["name"]}, headers=a["headers"])
    return r.json()["id"]


def test_bad_token_is_rejected(client):
    with client.websocket_connect("/ws?token=fake") as ws:
        with pytest.raises(WebSocketDisconnect) as err:
            ws.receive_json()
        assert err.value.code == 4001


def test_message_is_delivered_to_both_with_ticks(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = make_chat(client, jai, amit)

    with client.websocket_connect(ws_url(amit)) as wa, client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "hello amit"})

        got = recv_until(wa, "message")
        assert got["text"] == "hello amit"
        assert got["user"] == "jai"
        assert got["chat_id"] == chat_id

        own = recv_until(wj, "message")  # bhejne wale ko bhi wapas aata hai
        assert own["id"] == got["id"]

        # Amit online tha, toh double tick (delivered), par abhi padha nahi
        status = recv_until(wj, "status")
        assert status["delivered_upto"] == own["id"]
        assert status["read_upto"] == 0

        # Amit ne chat padhi, toh neela tick (read)
        wa.send_json({"type": "read", "chat_id": chat_id})
        status = recv_until(wj, "status")
        assert status["read_upto"] == own["id"]


def test_message_is_saved_in_database(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = make_chat(client, jai, amit)
    with client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "yaad rakhna"})
        recv_until(wj, "message")
    msgs = client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"]).json()
    assert [m["text"] for m in msgs] == ["yaad rakhna"]


def test_blank_message_is_ignored(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = make_chat(client, jai, amit)
    with client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "    "})
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "asli message"})
        assert recv_until(wj, "message")["text"] == "asli message"  # khaali wala beech mein nahi aaya
    assert len(client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"]).json()) == 1


def test_offline_user_gets_delivered_tick_when_coming_online(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = make_chat(client, jai, amit)
    with client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "tum offline ho"})
        own = recv_until(wj, "message")
        with client.websocket_connect(ws_url(amit)):  # amit ab online aaya
            status = recv_until(wj, "status")
            assert status["delivered_upto"] == own["id"]


def test_typing_event_reaches_the_other_user(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    chat_id = make_chat(client, jai, amit)
    with client.websocket_connect(ws_url(amit)) as wa, client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "typing", "chat_id": chat_id})
        event = recv_until(wa, "typing")
        assert event["user"] == "jai"
        assert event["chat_id"] == chat_id


def test_presence_online_and_last_seen(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    make_chat(client, jai, amit)  # contacts tabhi bante hain jab chat ho
    with client.websocket_connect(ws_url(amit)) as wa:
        with client.websocket_connect(ws_url(jai)) as wj:
            online = recv_until(wa, "presence")
            assert online["user"] == "jai"
            assert online["online"] is True

            # Jai ka tab band karo, par `with` se bahar nikalne se PEHLE.
            # Bahar nikalte hi test client server ka kaam beech mein kaat deta hai,
            # aur "offline" wala notification bhejne se pehle hi ruk jata hai.
            wj.close()
            offline = recv_until(wa, "presence")
            assert offline["user"] == "jai"
            assert offline["online"] is False
            assert offline["last_seen"]


def test_outsider_message_is_ignored(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    rahul = make_user("rahul")
    chat_id = make_chat(client, jai, amit)
    with client.websocket_connect(ws_url(amit)) as wa, \
         client.websocket_connect(ws_url(rahul)) as wr, \
         client.websocket_connect(ws_url(jai)) as wj:
        wr.send_json({"type": "message", "chat_id": chat_id, "text": "ghus gaya"})  # rahul is chat ka member nahi
        wj.send_json({"type": "message", "chat_id": chat_id, "text": "asli message"})
        assert recv_until(wa, "message")["text"] == "asli message"
    msgs = client.get(f"/api/chats/{chat_id}/messages", headers=amit["headers"]).json()
    assert [m["text"] for m in msgs] == ["asli message"]


def test_group_message_reaches_all_members(client, make_user, recv_until):
    jai = make_user("jai")
    amit = make_user("amit")
    rahul = make_user("rahul")
    gid = client.post("/api/groups", json={"name": "Goa", "members": ["amit", "rahul"]}, headers=jai["headers"]).json()["id"]
    with client.websocket_connect(ws_url(amit)) as wa, \
         client.websocket_connect(ws_url(rahul)) as wr, \
         client.websocket_connect(ws_url(jai)) as wj:
        wj.send_json({"type": "message", "chat_id": gid, "text": "sab ready?"})
        assert recv_until(wa, "message")["text"] == "sab ready?"
        assert recv_until(wr, "message")["text"] == "sab ready?"