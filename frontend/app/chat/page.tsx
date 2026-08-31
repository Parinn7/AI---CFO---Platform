/**
 * AI CFO chat (Phase 7.1–7.3, FR-6.1 / FR-6.2 / FR-6.3 / FR-6.5). Auth-guarded.
 * A conversational interface for asking questions about the company's finances,
 * with conversations saved and revisitable.
 *
 * **No model is connected yet.** The assistant returns a fixed placeholder that
 * quotes no figures; the provider lands in 7.4. The screen says so plainly
 * rather than looking like a working assistant that happens to be unhelpful.
 *
 * **Two disclosure panels, for the same reason.** *What the assistant can see*
 * (7.2) is the exact set of precomputed figures an answer is built from; *the
 * instructions it follows* (7.3) is the system prompt, verbatim. Both are on
 * this screen rather than hidden in the backend because the claims this project
 * makes about its AI — never calculates (architecture §4.1), explains in plain
 * language (FR-6.3), never poses as a licensed professional (FR-6.5) — are
 * claims a reader should be able to check rather than take on trust. Every
 * number in the first panel is a stored `kpi_snapshots` value and no
 * transaction appears in it; the rules that govern how it is used are in the
 * second.
 *
 * **The advisory disclaimer is shown permanently, not per answer (FR-6.5).**
 * The system prompt tells the model to say it in the answers that give advice,
 * where a person is reading. The standing line below the composer is the part
 * no model output can forget or remove — boilerplate appended to every message
 * would be read once and skipped forever, which is the opposite of clearly
 * indicating anything.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/contexts/AuthContext";
import { monthLong } from "@/lib/format";
import {
  ApiError,
  createChatSession,
  deleteChatSession,
  getChatContext,
  getChatPrompt,
  getChatSession,
  listChatSessions,
  listCompanies,
  postChatMessage,
  type ChatContext,
  type ChatMessage,
  type ChatPrompt,
  type ChatSession,
  type Company,
} from "@/lib/api";

/** Starter questions, phrased the way a founder would ask (FR-6.3's plain
 * language, applied to the prompts as well as the answers). */
const SUGGESTIONS = [
  "How long will my cash last?",
  "Why did my expenses jump last month?",
  "Can I afford to hire two engineers?",
  "Is my revenue growing fast enough?",
];

export default function ChatPage() {
  const { user, token, loading: authLoading } = useAuth();
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [context, setContext] = useState<ChatContext | null>(null);
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const co = (await listCompanies(token))[0] ?? null;
      setCompany(co);
      if (!co) return;
      // The figures an answer would be grounded in (7.2) and the rules it
      // answers under (7.3). Fetched here so both panels are populated before
      // anything is asked — what the assistant can see and what it's told to do
      // don't depend on having asked it something.
      const [list, ctx, prm] = await Promise.all([
        listChatSessions(co.id, token),
        getChatContext(co.id, token),
        getChatPrompt(co.id, token),
      ]);
      setSessions(list);
      setContext(ctx);
      setPrompt(prm);
      // Reopen the most recent conversation, so returning to the page picks up
      // where the user left off rather than staring at a blank screen.
      if (list.length > 0) {
        const detail = await getChatSession(list[0].id, token);
        setActiveId(detail.id);
        setMessages(detail.messages);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your conversations.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (token) load();
  }, [token, load]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  async function onSend(text: string) {
    const content = text.trim();
    if (!content || !token || !company || sending) return;

    setSending(true);
    setError(null);
    try {
      // A conversation is created lazily, on the first question, so browsing to
      // the page never leaves an empty session behind in the history.
      let sessionId = activeId;
      if (!sessionId) {
        const created = await createChatSession(company.id, token);
        sessionId = created.id;
        setActiveId(created.id);
        setSessions((prev) => [created, ...prev]);
      }

      setDraft("");
      const turn = await postChatMessage(sessionId, content, token);
      // Render the stored rows, not a local echo — what's on screen is then
      // exactly what's in the database.
      setMessages((prev) => [...prev, turn.user_message, turn.assistant_message]);
      setSessions((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                message_count: s.message_count + 2,
                preview: s.preview ?? turn.user_message.content,
              }
            : s,
        ),
      );

      // If the answer was grounded in a different snapshot than the panel is
      // showing — data changed in another tab, say — the panel is stale and
      // would be claiming the assistant saw figures it didn't.
      const used = turn.assistant_message.kpi_context_snapshot_id;
      if (used && used !== context?.context?.snapshot_id) {
        setContext(await getChatContext(company.id, token));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send that message.");
    } finally {
      setSending(false);
    }
  }

  async function onOpen(id: string) {
    if (!token || id === activeId) return;
    setError(null);
    try {
      const detail = await getChatSession(id, token);
      setActiveId(detail.id);
      setMessages(detail.messages);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't open that conversation.");
    }
  }

  function onNew() {
    // Nothing is created until the first question — see onSend.
    setActiveId(null);
    setMessages([]);
    setDraft("");
    setError(null);
  }

  async function onDelete(session: ChatSession) {
    if (!token) return;
    const label = session.preview ?? "this empty conversation";
    if (!window.confirm(`Delete "${label}"? Your financial data is untouched.`)) return;
    try {
      await deleteChatSession(session.id, token);
      setSessions((prev) => prev.filter((s) => s.id !== session.id));
      if (session.id === activeId) onNew();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete that conversation.");
    }
  }

  if (authLoading || !user || loading) {
    return (
      <main className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-black/50 dark:text-white/50">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex-1 w-full max-w-5xl mx-auto flex flex-col gap-6 p-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">AI CFO</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            {company
              ? `${company.name} — ask about your finances in plain language.`
              : "Ask about your finances in plain language."}
          </p>
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-sm">
          <Link href="/dashboard" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Dashboard
          </Link>
          <Link href="/scenarios" className="underline hover:no-underline text-black/60 dark:text-white/60">
            Scenarios
          </Link>
        </nav>
      </header>

      {/* Honest about what this does today (7.3 of 7.4). */}
      <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-500">
        <strong className="font-medium">Not connected yet.</strong> The
        conversation, the figures behind it and the instructions it answers
        under are all working — you can read both below. The language model
        itself isn&apos;t wired up, so it replies with a placeholder for now.
      </p>

      {error && (
        <p className="text-sm text-red-500" role="alert">
          {error}
        </p>
      )}

      {!company ? (
        <div className="rounded-xl border border-black/10 dark:border-white/15 p-8 text-center">
          <h2 className="text-lg font-semibold">Set up your company first</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-black/60 dark:text-white/60">
            The assistant answers against your company&apos;s figures, so it
            needs a company profile before it can be any use.
          </p>
          <Link
            href="/company"
            className="mt-5 inline-block rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Company profile
          </Link>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-[220px_1fr]">
          {/* Conversation list */}
          <aside className="flex flex-col gap-2">
            <button
              type="button"
              onClick={onNew}
              className="rounded-md border border-black/15 dark:border-white/20 px-3 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
            >
              New conversation
            </button>
            {sessions.length === 0 ? (
              <p className="px-1 py-2 text-xs text-black/50 dark:text-white/50">
                Your past conversations will appear here.
              </p>
            ) : (
              <ul className="flex flex-col gap-1">
                {sessions.map((s) => (
                  <li key={s.id} className="group flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => onOpen(s.id)}
                      className={`min-w-0 flex-1 rounded-md px-2 py-1.5 text-left text-xs transition-colors ${
                        s.id === activeId
                          ? "bg-black/10 dark:bg-white/15 font-medium"
                          : "hover:bg-black/5 dark:hover:bg-white/10"
                      }`}
                    >
                      <span className="block truncate">
                        {s.preview ?? "New conversation"}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(s)}
                      aria-label={`Delete conversation: ${s.preview ?? "empty"}`}
                      className="rounded px-1.5 py-1 text-xs text-black/30 dark:text-white/30 hover:text-red-600 dark:hover:text-red-500 transition-colors"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Transcript + composer */}
          <section className="flex flex-col gap-4">
            <div
              className="min-h-[22rem] rounded-xl border border-black/10 dark:border-white/15 p-5"
              aria-live="polite"
            >
              {messages.length === 0 ? (
                <div className="flex h-full flex-col justify-center gap-4 py-8 text-center">
                  <p className="text-sm text-black/60 dark:text-white/60">
                    Ask anything about your company&apos;s finances.
                  </p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => onSend(q)}
                        disabled={sending}
                        className="rounded-full border border-black/15 dark:border-white/20 px-3 py-1.5 text-xs hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-50 transition-colors"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <ul className="flex flex-col gap-4">
                  {messages.map((m) => (
                    <MessageBubble key={m.id} message={m} />
                  ))}
                  {sending && (
                    <li className="text-xs text-black/40 dark:text-white/40">Thinking…</li>
                  )}
                </ul>
              )}
              <div ref={endRef} />
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                onSend(draft);
              }}
              className="flex items-end gap-2"
            >
              <label htmlFor="chat-input" className="sr-only">
                Your question
              </label>
              <textarea
                id="chat-input"
                rows={2}
                value={draft}
                maxLength={4000}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  // Enter sends, Shift+Enter breaks a line — chat convention.
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    onSend(draft);
                  }
                }}
                placeholder="Ask about your runway, margins, spending…"
                className="w-full resize-none rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:focus:border-white/40"
              />
              <button
                type="submit"
                disabled={sending || !draft.trim()}
                className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {sending ? "Sending…" : "Send"}
              </button>
            </form>

            {context && <ContextPanel context={context} />}
            {prompt && <PromptPanel prompt={prompt} />}

            {/* FR-6.5 — shown wherever assistant-labelled text is rendered. */}
            <p className="text-xs text-black/50 dark:text-white/50">
              The AI CFO explains your figures — it never calculates them, and
              it is not a substitute for a licensed financial professional.
            </p>
          </section>
        </div>
      )}
    </main>
  );
}

/**
 * What the assistant can see (7.2, FR-6.2). Collapsed by default — it's
 * evidence, not the main event — but present on every visit.
 *
 * The figures are rendered by the backend and shown verbatim, including the
 * "Not applicable" cases and the reason each one is undefined. Reformatting
 * them here would mean the screen and the model were reading different words
 * for the same thing, which is exactly what this panel exists to rule out.
 */
function ContextPanel({ context }: { context: ChatContext }) {
  const ctx = context.context;

  return (
    <details className="rounded-lg border border-black/10 dark:border-white/15">
      <summary className="cursor-pointer select-none px-3.5 py-2.5 text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/[0.04] rounded-lg transition-colors">
        What the assistant can see
        <span className="ml-2 font-normal text-black/45 dark:text-white/45">
          {ctx
            ? `${ctx.figures.length} calculated figures · ${monthLong(
                ctx.period_start.slice(0, 7),
              )} – ${monthLong(ctx.period_end.slice(0, 7))}`
            : "nothing yet"}
        </span>
      </summary>

      <div className="border-t border-black/10 dark:border-white/15 px-3.5 py-3">
        {!ctx ? (
          <p className="text-xs text-black/60 dark:text-white/60">
            {context.unavailable_reason}{" "}
            <Link href="/data" className="underline hover:no-underline">
              Add your data
            </Link>
            .
          </p>
        ) : (
          <>
            <p className="text-xs text-black/60 dark:text-white/60">
              These are the only numbers the assistant is given, and it is never
              asked to work any of them out. Each one was calculated by the
              Financial Engine and stored — the same figures the dashboard
              shows. Your individual transactions are never sent.
            </p>
            <dl className="mt-3 grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
              {ctx.figures.map((f) => (
                <div key={f.key}>
                  <dt className="text-[0.7rem] uppercase tracking-wide text-black/45 dark:text-white/45">
                    {f.label}
                  </dt>
                  <dd className="text-sm font-medium">{f.value}</dd>
                  {f.note && (
                    <dd className="text-xs text-black/50 dark:text-white/50">
                      {f.note}
                    </dd>
                  )}
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[0.7rem] text-black/40 dark:text-white/40">
              Snapshot {ctx.snapshot_id.slice(0, 8)}, calculated{" "}
              {new Date(ctx.computed_at).toLocaleDateString()}. Covers{" "}
              {ctx.num_months} months of your recorded data.
            </p>
          </>
        )}
      </div>
    </details>
  );
}

/**
 * The instructions it follows (7.3, FR-6.3 / FR-6.5). Collapsed by default and
 * sitting beside the figures panel, because the two answer the same question
 * from opposite ends: that one is what the assistant is given, this one is what
 * it is told to do with it.
 *
 * The prompt is shown verbatim, in a monospace block, rather than summarised.
 * A paraphrase of a rule is not the rule — the whole point is that a reader can
 * check the claims on this page (never calculates, plain language, not a
 * licensed professional) against the text that actually enforces them.
 *
 * `system_prompt` is shown rather than `system_message`: the latter appends
 * this company's figures, which is exactly what the panel above already shows.
 */
function PromptPanel({ prompt }: { prompt: ChatPrompt }) {
  return (
    <details className="rounded-lg border border-black/10 dark:border-white/15">
      <summary className="cursor-pointer select-none px-3.5 py-2.5 text-xs font-medium hover:bg-black/[0.03] dark:hover:bg-white/[0.04] rounded-lg transition-colors">
        The instructions it follows
        <span className="ml-2 font-normal text-black/45 dark:text-white/45">
          the rules every answer is written under
        </span>
      </summary>

      <div className="border-t border-black/10 dark:border-white/15 px-3.5 py-3">
        <p className="text-xs text-black/60 dark:text-white/60">
          This is the full text sent with every question, word for word. It is
          what stops the assistant working numbers out for itself, keeps the
          language plain, and makes it say when an answer is edging into advice.
          Your last {prompt.max_history_messages} messages travel with it for
          continuity, along with the figures above.
        </p>
        <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-black/[0.03] dark:bg-white/[0.04] p-3 text-[0.7rem] leading-relaxed whitespace-pre-wrap font-mono text-black/70 dark:text-white/70">
          {prompt.system_prompt}
        </pre>
      </div>
    </details>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <li className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm whitespace-pre-wrap ${
          isUser
            ? "bg-foreground text-background"
            : "border border-black/10 dark:border-white/15"
        }`}
      >
        {!isUser && (
          <p className="mb-1 text-xs font-medium text-black/50 dark:text-white/50">
            AI CFO
          </p>
        )}
        {message.content}
      </div>
    </li>
  );
}
