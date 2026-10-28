from sqlalchemy import func, select

from datetime import datetime, timezone

from database import Conversation, Message, Participant, User


def iso(dt):
    # Hamesha same lambai ka format, taaki sort sahi chale
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def find_user(db, username):
    return db.query(User).filter(func.lower(User.username) == username.lower()).first()


def chat_members(db, chat_id):
    """Is chat ke sabhi members: [(id, username), ...]"""
    rows = (
        db.query(User.id, User.username)
        .join(Participant, Participant.user_id == User.id)
        .filter(Participant.conversation_id == chat_id)
        .all()
    )
    return [(r.id, r.username) for r in rows]


def get_or_create_private_chat(db, me, other):
    mine = select(Participant.conversation_id).where(Participant.user_id == me.id)
    theirs = select(Participant.conversation_id).where(Participant.user_id == other.id)
    chat = (
        db.query(Conversation)
        .filter(
            Conversation.is_group.is_(False),
            Conversation.id.in_(mine),
            Conversation.id.in_(theirs),
        )
        .first()
    )
    if chat:
        return chat
    chat = Conversation(is_group=False)
    db.add(chat)
    db.flush()  # id mil jaye
    db.add_all(
        [
            Participant(conversation_id=chat.id, user_id=me.id),
            Participant(conversation_id=chat.id, user_id=other.id),
        ]
    )
    db.commit()
    db.refresh(chat)
    return chat


def chat_summary(db, chat, me):
    other_name = None
    last_seen = None
    if chat.is_group:
        name = chat.name
    else:
        other = (
            db.query(User)
            .join(Participant, Participant.user_id == User.id)
            .filter(Participant.conversation_id == chat.id, User.id != me.id)
            .first()
        )
        name = other.username if other else "Unknown"
        other_name = other.username if other else None
        if other and other.last_seen:
            last_seen = iso(other.last_seen)

    last = (
        db.query(Message)
        .filter(Message.conversation_id == chat.id)
        .order_by(Message.id.desc())
        .first()
    )
    last_user = ""
    if last:
        last_user = db.query(User.username).filter(User.id == last.sender_id).scalar()

    # Unread = mere last_read_id ke baad ke wo messages jo kisi aur ne bheje
    mine = (
        db.query(Participant)
        .filter(Participant.conversation_id == chat.id, Participant.user_id == me.id)
        .first()
    )
    read_id = mine.last_read_id if mine else 0
    unread = (
        db.query(func.count(Message.id))
        .filter(
            Message.conversation_id == chat.id,
            Message.id > read_id,
            Message.sender_id != me.id,
        )
        .scalar()
    )
    return {
        "id": chat.id,
        "name": name,
        "is_group": chat.is_group,
        "other": other_name,
        "last_seen": last_seen,
        "unread": unread,
        "last_text": last.text if last else "",
        "last_user": last_user,
        "last_time": iso(last.created_at if last else chat.created_at),
    }


def list_chats(db, me):
    chats = (
        db.query(Conversation)
        .join(Participant, Participant.conversation_id == Conversation.id)
        .filter(Participant.user_id == me.id)
        .all()
    )
    result = [chat_summary(db, c, me) for c in chats]
    result.sort(key=lambda c: c["last_time"], reverse=True)
    return result


def get_messages(db, chat_id, me, limit=50):
    """Aakhri `limit` messages (purane se naye). Member nahi ho toh None."""
    if me.id not in [m[0] for m in chat_members(db, chat_id)]:
        return None
    rows = (
        db.query(Message, User.username)
        .join(User, User.id == Message.sender_id)
        .filter(Message.conversation_id == chat_id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    mark_read(db, chat_id, me.id)  # chat khol li = padh li

    # Mere bheje messages ke ticks: baaki logon ne kaun si id tak receive/padha
    r = chat_receipts(db, chat_id, me.id)
    result = []
    for m, name in rows:
        item = {"id": m.id, "user": name, "text": m.text, "time": iso(m.created_at)}
        if name == me.username:
            if m.id <= r["read_upto"]:
                item["status"] = "read"
            elif m.id <= r["delivered_upto"]:
                item["status"] = "delivered"
            else:
                item["status"] = "sent"
        result.append(item)
    return result


def save_message(db, chat_id, user_id, text):
    """Message save karo. Member nahi ho toh None, warna time aur receivers."""
    members = chat_members(db, chat_id)
    if user_id not in [m[0] for m in members]:
        return None
    msg = Message(conversation_id=chat_id, sender_id=user_id, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"id": msg.id, "time": iso(msg.created_at), "recipients": [m[1] for m in members]}


def mark_read(db, chat_id, user_id):
    """Is chat ke saare abhi tak ke messages padh liye (aur zaahir hai receive bhi)."""
    latest = (
        db.query(func.max(Message.id)).filter(Message.conversation_id == chat_id).scalar() or 0
    )
    p = (
        db.query(Participant)
        .filter(Participant.conversation_id == chat_id, Participant.user_id == user_id)
        .first()
    )
    if p:
        if latest > p.last_read_id:
            p.last_read_id = latest
        if latest > p.last_delivered_id:
            p.last_delivered_id = latest
        db.commit()


def mark_delivered(db, chat_id, usernames, upto_id):
    """In users ke paas message `upto_id` tak pahunch gaya."""
    rows = (
        db.query(Participant)
        .join(User, User.id == Participant.user_id)
        .filter(Participant.conversation_id == chat_id, User.username.in_(usernames))
        .all()
    )
    for p in rows:
        if upto_id > p.last_delivered_id:
            p.last_delivered_id = upto_id
    db.commit()


def mark_all_delivered(db, user_id):
    """User online aaya: uski saari chats ke pending messages 'delivered' ho gaye.
    Wo chat ids wapas do jinme kuch badla."""
    changed = []
    parts = db.query(Participant).filter(Participant.user_id == user_id).all()
    for p in parts:
        latest = (
            db.query(func.max(Message.id))
            .filter(Message.conversation_id == p.conversation_id)
            .scalar()
            or 0
        )
        if latest > p.last_delivered_id:
            p.last_delivered_id = latest
            changed.append(p.conversation_id)
    db.commit()
    return changed


def chat_receipts(db, chat_id, viewer_id):
    """Viewer ke bheje messages ka haal: baaki sabke paas kaun si id tak pahuncha / padha gaya."""
    others = (
        db.query(Participant)
        .filter(Participant.conversation_id == chat_id, Participant.user_id != viewer_id)
        .all()
    )
    if not others:
        return {"delivered_upto": 0, "read_upto": 0}
    return {
        "delivered_upto": min(p.last_delivered_id for p in others),
        "read_upto": min(p.last_read_id for p in others),
    }


def receipts_for_members(db, chat_id):
    """Har member ke liye uska apna ticks ka haal: [(username, receipts), ...]"""
    return [(name, chat_receipts(db, chat_id, uid)) for uid, name in chat_members(db, chat_id)]


def set_last_seen(db, user_id):
    """Abhi ka time 'last seen' mein save karo aur wapas do."""
    now = datetime.now(timezone.utc)
    user = db.get(User, user_id)
    if user:
        user.last_seen = now
        db.commit()
    return iso(now)


def contacts(db, user_id):
    """Jin logon ke saath is user ki koi chat hai, unke usernames."""
    mine = select(Participant.conversation_id).where(Participant.user_id == user_id)
    rows = (
        db.query(User.username)
        .join(Participant, Participant.user_id == User.id)
        .filter(Participant.conversation_id.in_(mine), User.id != user_id)
        .distinct()
        .all()
    )
    return [r.username for r in rows]