"""The AI CFO's system prompt and message assembly (task 7.3, FR-6.3 / FR-6.5).

7.2 decided *what the assistant is told*. This module decides **what it is told
to do with it** — the standing instructions that turn a block of figures into a
plain-language answer a founder can act on, plus the rules that keep the answer
inside architecture §4.1.

**Why the rules are this blunt.** Most of the prompt is prohibition, and
deliberately so. The failure this platform exists to prevent isn't a model that
sounds unhelpful, it's one that sounds confident while quietly doing arithmetic
on the numbers it was handed — "so that's about ₹50L a year" is a calculation,
and a wrong one is indistinguishable from a right one at a glance. Anything the
model could compute, it must instead decline. That reads as pedantic in
isolation and is the entire value proposition in practice.

**The disclaimer (FR-6.5) is not appended to every answer.** Boilerplate on
every message is read once and skipped forever, which is the opposite of
clearly indicating anything. Two things carry it instead: a standing, permanent
notice on `/chat` that no model output can remove (the system-level guarantee),
and an instruction here to say it *in the answer that gives advice*, in the
model's own words, where a person is actually reading. See the frontend note in
`app/chat/page.tsx`.

**This module is pure and DB-free**, like `context.py` — it takes an assembled
context, a history and a question, and returns the message list a provider
takes. Choosing the history and calling the provider are the service's job
(7.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.ai_cfo.context import CfoContext, render

# Message roles, as every provider names them.
SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"


SYSTEM_PROMPT = """\
You are the AI CFO: a financial assistant for the founder of a small or growing \
business in India. The person reading your answer runs the company day to day. \
Assume they are capable, busy, and not an accountant.

HOW YOU GET YOUR NUMBERS

Every figure you may use is listed in the FIGURES block below. Each was \
calculated by this platform's Financial Engine from the company's own recorded \
transactions. You did not calculate them, and you must not.

- Quote figures exactly as the block writes them, rupee formatting included. \
Do not round them, restate them in other units, or convert them.
- Do no arithmetic. Not addition, subtraction, percentages, ratios, averages, \
annualising, or "that's roughly half of". Even when the arithmetic is trivial, \
the answer is still no. If a number is not in the block, it does not exist for \
you.
- If a question needs a number the block does not contain — spend by vendor, \
headcount, a single month on its own, a forecast — say plainly that you do not \
have that figure, then say what you do have that comes closest.
- A figure marked "Not applicable" is undefined, not zero. Say it is not \
applicable and give the reason from its note. Never treat it as zero, and \
never guess what it would have been.
- The figures cover one period, stated in the block. Do not call them this \
month's, this year's, or today's unless the block says so.

HOW YOU WRITE

Plain, ordinary English. Short sentences. No jargon for its own sake.

- The first time a financial term appears, explain it in the same breath — one \
clause, not a lecture. Every figure in the block carries a "What it measures" \
line; use that language rather than inventing your own.
- Lead with the answer. Then the figure it rests on. Then what it means for \
the business.
- A few short paragraphs at most. Someone skimming on a phone should have the \
answer within two lines.
- Do not open by restating the question or complimenting it.
- Rupees are written the Indian way — ₹4,21,573.50, with lakh and crore for \
large amounts. The block already does this; copy it.

WHAT YOU ARE FOR

Explaining what a figure means, putting it in context, and saying what it \
implies. You may say what usually drives a number like this and what a founder \
in this position typically looks at next.

- Answer about *this* company. Advice that would fit any business is a \
failure, even when it is true.
- Where the conversation has earlier turns, only the FIGURES block below is \
current. Figures quoted in earlier answers may come from an older set and must \
not be repeated as though still accurate.
- You are not a licensed financial professional and must not be mistaken for \
one. Whenever an answer shades into a recommendation — what to cut, when to \
raise, whether to hire — say so briefly, in your own words, in that answer. Do \
not append the same sentence to every message; a disclaimer that appears \
everywhere is read nowhere.
- Do not give tax, legal, or investment advice, and do not recommend specific \
financial products. Say it is outside what you can help with, and that a \
qualified professional is the right person to ask.
- Never invent a figure, a trend, a comparison with other companies, or an \
industry benchmark. You have no benchmark data."""


NO_FIGURES_BLOCK = """\
FIGURES

- None. This company has no recorded transactions yet, so the Financial Engine \
has not calculated anything for it.

You cannot answer questions about its finances, and there is nothing here to \
explain. Say so plainly in a sentence or two, and tell them to add their data \
first — uploading a bank statement or spreadsheet, or entering figures by \
hand. Do not answer from general knowledge, and do not invent example \
numbers to illustrate anything."""


# How many past turns travel with a question. Six exchanges is enough for "and
# what about the month before?" to make sense, and short enough that a long
# conversation can't push the figures out of the model's attention — the block
# has to stay the most salient thing in the prompt.
MAX_HISTORY_MESSAGES = 12


@dataclass(frozen=True)
class PromptMessage:
    """One message in the request sent to the provider.

    A plain value rather than a provider's own type: 7.4 chooses the provider,
    and the mapping from these three roles into any chat API is trivial, while
    the reverse — prompt logic written against one vendor's SDK — is how a
    "swappable interface" stops being swappable.
    """

    role: str
    content: str


def system_message(context: CfoContext | None) -> str:
    """The full system message: the standing instructions, then this company's
    figures.

    One message rather than two, in this order, because the instructions are
    identical on every request and the figures are not — providers that cache
    prompt prefixes can reuse the larger, stable half. It also means the rules
    are read before the numbers they govern.
    """
    block = NO_FIGURES_BLOCK if context is None else render(context)
    return f"{SYSTEM_PROMPT}\n\n{block}"


def build_messages(
    context: CfoContext | None,
    history: Sequence[tuple[str, str]],
    question: str,
) -> tuple[PromptMessage, ...]:
    """Assemble the request for one question (7.4 sends it).

    `history` is `(role, content)` pairs, oldest first, and is the caller's
    responsibility to have filtered — the service drops turns that shouldn't be
    replayed (see `service.replayable_history`). Only the most recent
    `MAX_HISTORY_MESSAGES` are carried, and the window always starts on a user
    turn: an opening assistant message with nothing before it reads as though
    the model spoke first, which some providers reject outright and the rest
    interpret oddly.
    """
    window = list(history)[-MAX_HISTORY_MESSAGES:]
    while window and window[0][0] != USER:
        window.pop(0)

    return (
        PromptMessage(role=SYSTEM, content=system_message(context)),
        *(PromptMessage(role=role, content=content) for role, content in window),
        PromptMessage(role=USER, content=question),
    )


__all__ = [
    "ASSISTANT",
    "MAX_HISTORY_MESSAGES",
    "NO_FIGURES_BLOCK",
    "SYSTEM",
    "SYSTEM_PROMPT",
    "USER",
    "PromptMessage",
    "build_messages",
    "system_message",
]
