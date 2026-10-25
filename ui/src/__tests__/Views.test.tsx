import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import type { BatchDetail, Sentence, Session } from "../types";
import { AskView } from "../views/Ask";
import { DirectionsView } from "../views/Directions";
import { DocumentsView } from "../views/Documents";
import { GistView } from "../views/Gist";
import { ReviewView } from "../views/Review";
import type { ViewProps } from "../views/shared";

const analyst: Session = { username: "lawyer", role: "analyst", token: null };
const viewer: Session = { username: "intern", role: "viewer", token: null };
const props = (over: Partial<ViewProps> = {}): ViewProps => ({ matterId: "m1", asOf: 2, latest: 2, today: "", session: analyst, onOpen: vi.fn(), onChanged: vi.fn(), ...over });
const sent = (over: Partial<Sentence>): Sentence => ({ id: "s", text: "t", status: "VERIFIED", state: "CURRENT", kind: "fact", citations: [], ...over });

afterEach(() => vi.restoreAllMocks());

describe("GistView", () => {
  it("shows an empty state before the first batch", () => {
    render(<GistView {...props({ latest: 0, asOf: 0 })} />);
    expect(screen.getByText("No documents yet")).toBeInTheDocument();
  });

  it("groups facts, calls out disputes and lists what is no longer valid", async () => {
    vi.spyOn(api, "view").mockResolvedValue({
      as_of_batch_seq: 2, plan: "GIST", notes: [],
      sentences: [sent({ id: "M-0", kind: "meta", state: "INFO", text: "Vardhan v Kestrel" }), sent({ id: "a", text: "Delivery 31 Jul 2024" }), sent({ id: "b", text: "Notice received", state: "DISPUTED" }), sent({ id: "c", text: "Notice not received", state: "DISPUTED" })],
      extras: { sections: { "Contract terms": ["a"], Notices: ["b", "c"] }, superseded: [{ id: "x", text: "Delivery 30 Jun 2024", superseded_by_doc: "Amendment No. 1, p.1", superseded_by: "Delivery 31 Jul 2024" }] },
    });
    render(<GistView {...props()} />);
    expect(await screen.findByText("Contract terms")).toBeInTheDocument();
    expect(screen.getByText(/2 point\(s\) are disputed/)).toBeInTheDocument();
    expect(screen.getByText(/No longer valid \(1\)/)).toBeInTheDocument();
  });

  it("explains an as-of view and offers a retry on errors", async () => {
    const spy = vi.spyOn(api, "view").mockRejectedValueOnce(new ApiError(500, { detail: "boom", request_id: "r9" })).mockResolvedValue({ as_of_batch_seq: 1, plan: "GIST", notes: [], sentences: [], extras: { sections: {} } });
    render(<GistView {...props({ asOf: 1 })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Showing what the system understood after batch 1/)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(2);
  });
});

describe("DirectionsView", () => {
  const dir = (id: string, status: string, due: string | null) => sent({ id, kind: "direction", text: `Direction ${id}`, meta: { status, due_date: due, step: "replication", kind: "DIRECTION", responsible: "Plaintiff" } });
  it("filters by status and shows computed due dates", async () => {
    vi.spyOn(api, "view").mockResolvedValue({ as_of_batch_seq: 2, plan: "DIRECTIONS", today: "2025-10-20", notes: [], extras: {}, sentences: [dir("a", "OVERDUE", "2025-10-10"), dir("b", "PENDING", "2025-10-24")] });
    render(<DirectionsView {...props()} />);
    expect(await screen.findByText("Direction a")).toBeInTheDocument();
    expect(screen.getByText("10 Oct 2025")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Overdue" }));
    expect(screen.queryByText("Direction b")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Complied" }));
    expect(screen.getByText("Nothing matches this filter")).toBeInTheDocument();
  });
});

describe("AskView", () => {
  it("shows not-found answers, removed unverified statements and the trace id", async () => {
    vi.spyOn(api, "ask").mockResolvedValue({
      question: "q", as_of_batch_seq: 2, intents: ["FACTUAL_QA"], routed_by: "RULES", answer_sentences: [], sections: [{ plan: "FACTUAL_QA", title: "Answer", sentences: [], notes: [], extras: {} }],
      not_found: ["No document records the counsel."], superseded_notes: [], unverified: [{ id: "1", text: "x", reasons: ["quote not found"] }], notes: [], mode: "extractive", trace_id: "trace-123",
    });
    render(<AskView {...props()} />);
    await userEvent.type(screen.getByLabelText("Question"), "Who is the counsel?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/No document records the counsel/)).toBeInTheDocument();
    expect(screen.getByText(/unverified statement\(s\) removed/)).toBeInTheDocument();
    expect(screen.getByText(/extractive answer/)).toBeInTheDocument();
    expect(screen.getByText(/trace-123/)).toBeInTheDocument();
  });

  it("runs a suggested question and surfaces server errors", async () => {
    const ask = vi.spyOn(api, "ask").mockRejectedValue(new ApiError(422, { detail: "the question is empty" }));
    render(<AskView {...props()} />);
    await userEvent.click(screen.getByRole("button", { name: "What changed since the last batch?" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the question is empty");
    expect(ask).toHaveBeenCalledWith("m1", "What changed since the last batch?", 2, undefined);
  });

  it("is disabled until a batch exists", () => {
    render(<AskView {...props({ latest: 0, asOf: 0 })} />);
    expect(screen.getByLabelText("Question")).toBeDisabled();
    expect(screen.getByText(/Upload and commit a batch first/)).toBeInTheDocument();
  });
});

describe("DocumentsView", () => {
  const batch = (over: Partial<BatchDetail> = {}): BatchDetail => ({ batch_seq: 1, label: "Initial", status: "OPEN", documents: [], duplicates: [], progress: {}, reconcile: null, ...over });
  const mockMatter = (batches: any[]) => vi.spyOn(api, "matter").mockResolvedValue({ matter_id: "m1", batches } as any);

  it("uploads files and reports duplicates and rejections per file", async () => {
    mockMatter([{ batch_seq: 1, status: "OPEN" }]);
    vi.spyOn(api, "batch").mockResolvedValue(batch());
    const upload = vi.spyOn(api, "upload").mockResolvedValue({ accepted: [{ document_id: "d", filename: "a.pdf" }], duplicates: [{ filename: "b.pdf", duplicate_of: "d" }], rejected: [{ filename: "c.exe", code: "unsupported_media_type", reason: "executable content is not accepted" }] });
    render(<DocumentsView {...props()} />);
    const input = await screen.findByTestId("file-input");
    await userEvent.setup({ applyAccept: false }).upload(input, [new File(["x"], "a.pdf"), new File(["y"], "b.pdf"), new File(["z"], "c.exe")]);
    await userEvent.click(screen.getByRole("button", { name: /Upload 3 file/ }));
    expect(await screen.findByText("1 file(s) uploaded.")).toBeInTheDocument();
    expect(screen.getByText(/b.pdf is already in this matter and was skipped/)).toBeInTheDocument();
    expect(screen.getByText(/c.exe: executable content is not accepted/)).toBeInTheDocument();
    expect(upload).toHaveBeenCalledOnce();
  });

  it("cannot commit an empty batch; commits when there are documents", async () => {
    mockMatter([{ batch_seq: 1, status: "OPEN" }]);
    const b = vi.spyOn(api, "batch").mockResolvedValue(batch());
    const commit = vi.spyOn(api, "commit").mockResolvedValue({ status: "PROCESSING" });
    const { rerender } = render(<DocumentsView {...props()} />);
    expect(await screen.findByRole("button", { name: "Commit batch" })).toBeDisabled();
    b.mockResolvedValue(batch({ documents: [{ document_id: "d", original_filename: "a.pdf", title: "A", status: "EXTRACTED", document_type: "CONTRACT", document_date: "2023-01-12", authority_class: "BILATERAL", current_step: null, error_message: null, needs_review: false, total_pages: 1 }] }));
    rerender(<DocumentsView {...props({ matterId: "m1x" })} />);
    const btn = await screen.findByRole("button", { name: "Commit batch" });
    await waitFor(() => expect(btn).toBeEnabled());
    await userEvent.click(btn);
    expect(commit).toHaveBeenCalledWith("m1x", 1);
  });

  it("shows failures plainly and hides upload controls from viewers", async () => {
    mockMatter([{ batch_seq: 1, status: "OPEN" }]);
    vi.spyOn(api, "batch").mockResolvedValue(batch({ documents: [{ document_id: "d", original_filename: "locked.pdf", title: "locked", status: "FAILED", document_type: null, document_date: null, authority_class: null, current_step: null, error_message: "the PDF is password-protected", needs_review: false, total_pages: null }] }));
    render(<DocumentsView {...props({ session: viewer })} />);
    expect(await screen.findByText("the PDF is password-protected")).toBeInTheDocument();
    expect(screen.queryByTestId("file-input")).toBeNull();
    expect(screen.queryByRole("button", { name: "New batch" })).toBeNull();
  });

  it("shows progress while a batch is processing", async () => {
    mockMatter([{ batch_seq: 1, status: "PROCESSING" }]);
    vi.spyOn(api, "batch").mockResolvedValue(batch({ status: "PROCESSING", reconcile: "QUEUED", documents: [{ document_id: "d", original_filename: "a.pdf", title: "A", status: "PROCESSING", document_type: null, document_date: null, authority_class: null, current_step: "EXTRACT (running)", error_message: null, needs_review: false, total_pages: null }] }));
    render(<DocumentsView {...props()} />);
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText("EXTRACT (running)")).toBeInTheDocument();
  });
});

describe("ReviewView", () => {
  const item = { kind: "FACT" as const, id: "a1", title: "Notice received: true", reason: "no rule covers this conflict", state: "DISPUTED", document: "Plaint", document_id: "d1", page: 2, quote: "q", batch_seq: 1 };
  it("records a reviewer decision with a reason", async () => {
    vi.spyOn(api, "reviewQueue").mockResolvedValue({ count: 1, items: [item] });
    const fn = vi.spyOn(api, "reviewFact").mockResolvedValue({ state: "ACTIVE" });
    const onChanged = vi.fn();
    render(<ReviewView {...props({ onChanged })} />);
    await userEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    const dlg = screen.getByRole("dialog");
    await userEvent.selectOptions(within(dlg).getByLabelText("Decision"), "SUPERSEDE_OTHERS");
    expect(within(dlg).getByRole("button", { name: "Save decision" })).toBeDisabled();
    await userEvent.type(within(dlg).getByLabelText(/Reason/), "service record confirms receipt");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save decision" }));
    expect(fn).toHaveBeenCalledWith("a1", { action: "SUPERSEDE_OTHERS", reason: "service record confirms receipt", value: undefined });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("needs a value to correct a fact and shows server refusals", async () => {
    vi.spyOn(api, "reviewQueue").mockResolvedValue({ count: 1, items: [item] });
    vi.spyOn(api, "reviewFact").mockRejectedValue(new ApiError(409, { detail: "this fact has already ended" }));
    render(<ReviewView {...props()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    const dlg = screen.getByRole("dialog");
    await userEvent.selectOptions(within(dlg).getByLabelText("Decision"), "CORRECT_VALUE");
    await userEvent.type(within(dlg).getByLabelText(/Reason/), "typo");
    expect(within(dlg).getByRole("button", { name: "Save decision" })).toBeDisabled();
    await userEvent.type(within(dlg).getByLabelText("Corrected value"), "true");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save decision" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("already ended");
  });

  it("is empty-state friendly and read-only for viewers", async () => {
    vi.spyOn(api, "reviewQueue").mockResolvedValueOnce({ count: 0, items: [] });
    const { unmount } = render(<ReviewView {...props()} />);
    expect(await screen.findByText("Nothing needs review")).toBeInTheDocument();
    unmount();
    vi.spyOn(api, "reviewQueue").mockResolvedValue({ count: 1, items: [item] });
    render(<ReviewView {...props({ session: viewer })} />);
    await screen.findByText("Notice received: true");
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });
});
