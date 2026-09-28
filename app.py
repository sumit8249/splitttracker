"""SplitSnap: a receipt-reading bill splitter powered by Gemini and Streamlit."""

from __future__ import annotations

from email.message import EmailMessage
import smtplib
from typing import Any

import streamlit as st
from google import genai
from google.genai import types

from bill_split import (
    calculate_itemized_split,
    format_amount,
    normalize_receipt,
    parse_assistant_response,
    split_equally,
)
from prompts import SUMMARY_REQUEST_PROMPT, SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE


MODEL_NAME = "gemini-2.5-flash"

st.set_page_config(
    page_title="SplitSnap | Receipt & bill splitter",
    page_icon=":material/receipt_long:",
    layout="centered",
)


def read_secret(name: str) -> str:
    """Return a configured Streamlit secret without raising on missing keys."""
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, RuntimeError):
        return ""


GEMINI_API_KEY = read_secret("GEMINI_API_KEY")
GMAIL_ADDRESS = read_secret("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = read_secret("GMAIL_APP_PASSWORD")


@st.cache_resource
def get_gemini_client(api_key: str) -> genai.Client:
    """Reuse one Gemini client across Streamlit reruns."""
    return genai.Client(api_key=api_key)


def initialize_session() -> None:
    """Create the per-visitor state in one place."""
    defaults: dict[str, Any] = {
        "onboarded": False,
        "messages": [],
        "receipt": None,
        "receipt_version": 0,
        "last_split_summary": "",
        "email_status": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_message(message: dict[str, Any]) -> None:
    """Render a saved chat turn, including an optional uploaded receipt."""
    with st.chat_message(message["role"]):
        if message.get("kind") == "image":
            st.image(message["content"], caption="Receipt image", width=320)
        if message.get("text"):
            st.markdown(message["text"])


def conversation_text(messages: list[dict[str, Any]]) -> str:
    """Build a compact, image-safe transcript for email summarization."""
    transcript: list[str] = []
    for message in messages:
        role = "You" if message["role"] == "user" else "SplitSnap"
        text = message.get("text", "")
        if message.get("kind") == "image":
            text = f"{text}\n[Receipt photo attached]".strip()
        if text:
            transcript.append(f"{role}: {text}")
    return "\n".join(transcript)


def send_email(to_address: str, subject: str, body: str) -> None:
    """Send a user-requested summary with a Gmail app password over TLS."""
    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = GMAIL_ADDRESS
    email["To"] = to_address
    email.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(email)


def render_onboarding() -> None:
    st.title("SplitSnap", icon=":material/receipt_long:")
    st.write("Turn a receipt photo into a clear, fair bill split.")
    st.caption("Your name and email stay in this browser session.")

    with st.form("onboarding_form", clear_on_submit=False):
        name = st.text_input("Your name", placeholder="Alex")
        email = st.text_input(
            "Email for your split summary",
            placeholder="you@example.com",
            help="SplitSnap sends a summary only after you press the email button.",
        )
        submitted = st.form_submit_button(
            "Start splitting", type="primary", icon=":material/arrow_forward:"
        )

    if submitted:
        if not name.strip() or not email.strip() or "@" not in email:
            st.warning("Enter your name and a valid email address to continue.")
        else:
            st.session_state.name = name.strip()
            st.session_state.email = email.strip()
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "kind": "text",
                    "text": WELCOME_MESSAGE_TEMPLATE.format(name=name.strip()),
                }
            ]
            st.session_state.onboarded = True
            st.rerun()


def get_receipt_items(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return editable rows for the item split table."""
    attendees = st.session_state.get("attendees", st.session_state.get("name", ""))
    default_people = ", ".join(
        person.strip() for person in str(attendees).split(",") if person.strip()
    )
    return [
        {
            "item": item["name"],
            "amount": float(item["amount"]),
            "participants": default_people,
        }
        for item in receipt.get("items", [])
    ]


def render_split_builder() -> None:
    receipt = st.session_state.get("receipt")
    if not receipt:
        return

    st.subheader("Review and split", anchor=False)
    currency = receipt.get("currency", "USD")
    items = receipt.get("items", [])
    detected_total = receipt.get("total")
    items_total = sum((item["amount"] for item in items), start=0)
    default_total = detected_total if detected_total is not None else items_total

    if not items and detected_total is None:
        st.caption("No item totals were found. Add a receipt photo or enter a bill total below.")

    version = st.session_state.receipt_version
    split_method = st.segmented_control(
        "Split method",
        options=["Evenly", "By item"],
        default="Evenly",
        key=f"split_method_{version}",
    )
    with st.form(f"split_form_{version}"):
        people_text = st.text_input(
            "People sharing the bill",
            value=st.session_state.get("attendees", st.session_state.get("name", "")),
            help="Separate names with commas, for example: Alex, Sam, Priya.",
        )

        if split_method == "By item":
            st.caption("Edit amounts and list who shared each item, separated by commas.")
            initial_rows = get_receipt_items(receipt) or [
                {"item": "", "amount": 0.0, "participants": ""}
            ]
            edited_rows = st.data_editor(
                initial_rows,
                key=f"item_editor_{version}",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={
                    "item": st.column_config.TextColumn("Item", required=True),
                    "amount": st.column_config.NumberColumn(
                        f"Amount ({currency})", min_value=0.0, format="%.2f"
                    ),
                    "participants": st.column_config.TextColumn("Shared by"),
                },
            )
            total = None
        else:
            total = st.number_input(
                f"Bill total ({currency})",
                min_value=0.0,
                value=float(default_total),
                step=1.0,
                format="%.2f",
                key=f"bill_total_{version}",
            )
            edited_rows = []

        calculate = st.form_submit_button(
            "Calculate split", type="primary", icon=":material/calculate:"
        )

    if calculate:
        attendees = [person.strip() for person in people_text.split(",") if person.strip()]
        if not attendees:
            st.warning("Add at least one person to calculate the split.")
        elif split_method == "By item":
            shares = calculate_itemized_split(edited_rows, attendees)
            if not any(shares.values()):
                st.warning("Add at least one item with an amount greater than zero.")
            else:
                st.session_state.attendees = people_text
                st.session_state.last_split_summary = "\n".join(
                    [
                        f"{person}: {format_amount(amount, currency)}"
                        for person, amount in shares.items()
                    ]
                )
                st.session_state.last_split_method = "By item"
                st.session_state.last_split_total = sum(shares.values(), start=0)
                st.rerun()
        else:
            shares = split_equally(total or 0, attendees)
            st.session_state.attendees = people_text
            st.session_state.last_split_summary = "\n".join(
                [
                    f"{person}: {format_amount(amount, currency)}"
                    for person, amount in shares.items()
                ]
            )
            st.session_state.last_split_method = "Evenly"
            st.session_state.last_split_total = sum(shares.values(), start=0)
            st.rerun()

    if st.session_state.get("last_split_summary"):
        st.success(f"Split ready · {st.session_state.last_split_method}")
        st.code(st.session_state.last_split_summary, language=None)
        st.caption(
            f"Total assigned: {format_amount(st.session_state.last_split_total, currency)}"
        )


def main() -> None:
    initialize_session()

    if not st.session_state.onboarded:
        render_onboarding()
        return

    header, action = st.columns([3, 1], vertical_alignment="center")
    with header:
        st.title("SplitSnap", icon=":material/receipt_long:")
    with action:
        ready_to_email = len(st.session_state.messages) > 1
        email_clicked = st.button(
            "Email summary",
            icon=":material/mail:",
            disabled=not ready_to_email,
            width="stretch",
            help="Summarize this conversation and email it to you.",
        )

    st.caption(f"Signed in as {st.session_state.name} · summary goes to {st.session_state.email}")
    if not GEMINI_API_KEY:
        st.warning(
            "Gemini is not configured yet. Add GEMINI_API_KEY to "
            ".streamlit/secrets.toml, then refresh this page."
        )

    for message in st.session_state.messages:
        render_message(message)

    chat_submission = st.chat_input(
        "Describe a bill or attach a receipt photo",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
        key="receipt_chat_input",
    )

    if chat_submission:
        photo = chat_submission.files[0] if chat_submission.files else None
        text = (chat_submission.text or "").strip()
        parts: list[Any] = []

        with st.chat_message("user"):
            if photo is not None:
                photo_bytes = photo.getvalue()
                st.image(photo_bytes, caption="Receipt image", width=320)
                st.session_state.messages.append(
                    {"role": "user", "kind": "image", "content": photo_bytes, "text": text}
                )
                parts.append(
                    types.Part.from_bytes(data=photo_bytes, mime_type=photo.type or "image/jpeg")
                )
            if text:
                st.markdown(text)
                st.session_state.messages.append(
                    {"role": "user", "kind": "text", "text": text}
                )

        if photo is not None and not text:
            parts.append(
                "Read this receipt. Identify the currency, line items and their amounts, "
                "and the final total. If a value is unclear, say so rather than guessing."
            )
        elif text:
            parts.append(text)

        if not GEMINI_API_KEY:
            with st.chat_message("assistant"):
                st.error("Add a Gemini API key to enable receipt analysis and chat.")
        else:
            try:
                if "chat" not in st.session_state:
                    client = get_gemini_client(GEMINI_API_KEY)
                    st.session_state.chat = client.chats.create(
                        model=MODEL_NAME,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json",
                        ),
                    )
                with st.chat_message("assistant"):
                    with st.spinner("Reading the bill…"):
                        response = st.session_state.chat.send_message(parts)
                    answer, receipt_payload = parse_assistant_response(response.text or "")
                    st.markdown(answer)
                st.session_state.messages.append(
                    {"role": "assistant", "kind": "text", "text": answer}
                )
                if receipt_payload:
                    st.session_state.receipt = normalize_receipt(receipt_payload)
                    st.session_state.receipt_version += 1
                    st.session_state.last_split_summary = ""
            except Exception as error:  # Keep API errors visible and recoverable in the UI.
                with st.chat_message("assistant"):
                    st.error(f"Gemini could not process that request: {error}")

    render_split_builder()

    if email_clicked:
        if not GEMINI_API_KEY:
            st.error("Configure Gemini before requesting a conversation summary.")
        elif not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            st.error("Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your Streamlit secrets first.")
        else:
            split_context = st.session_state.get("last_split_summary", "Not calculated yet.")
            prompt = (
                f"{SUMMARY_REQUEST_PROMPT}\n\nConversation:\n"
                f"{conversation_text(st.session_state.messages)}\n\n"
                f"Current split ({st.session_state.get('last_split_method', 'not calculated')}):\n"
                f"{split_context}"
            )
            try:
                with st.spinner("Preparing and emailing your summary…"):
                    client = get_gemini_client(GEMINI_API_KEY)
                    response = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json",
                        ),
                    )
                    summary, _ = parse_assistant_response(response.text or "")
                    send_email(
                        st.session_state.email,
                        "Your SplitSnap bill summary",
                        summary,
                    )
                st.success(f"Summary sent to {st.session_state.email}.")
            except Exception as error:
                st.error(f"Could not send the summary. Check your Gemini and Gmail settings. Details: {error}")

    with st.sidebar:
        st.subheader("Quick guide")
        st.markdown(
            "1. Upload a receipt photo or describe the bill.\n"
            "2. Review the items Gemini found.\n"
            "3. Choose an even or item-based split.\n"
            "4. Email yourself the conversation summary."
        )
        st.caption("AI estimates can be wrong. Check every amount before sharing.")


main()