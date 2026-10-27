from sqlalchemy import func, select

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
    if chat.is_group:
        name = chat.name
    else:
        other = (
            db.query(User.username)
            .join(Participant, Participant.user_id == User.id)
            .filter(Participant.conversation_id == chat.id, User.id != me.id)
            .first()
        )
        name = other.username if other else "Unknown"
    last = (
        db.query(Message)
        .filter(Message.conversation_id == chat.id)
        .order_by(Message.id.desc())
        .first()
    )
    last_user = ""
    if last:
        last_user = db.query(User.username).filter(User.id == last.sender_id).scalar()
    return {
        "id": chat.id,
        "name": name,
        "is_group": chat.is_group,
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
    return [{"user": name, "text": m.text, "time": iso(m.created_at)} for m, name in rows]


def save_message(db, chat_id, user_id, text):
    """Message save karo. Member nahi ho toh None, warna time aur receivers."""
    members = chat_members(db, chat_id)
    if user_id not in [m[0] for m in members]:
        return None
    msg = Message(conversation_id=chat_id, sender_id=user_id, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"time": iso(msg.created_at), "recipients": [m[1] for m in members]}