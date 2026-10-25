import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SentenceItem, SentenceList } from "../components/Sentences";
import type { Sentence } from "../types";

const base: Sentence = {
  id: "F-1", text: "Delivery / completion date (MSA-2023): 31 Jul 2024", status: "VERIFIED", state: "CURRENT", kind: "fact",
  citations: [{ document_id: "d1", document_title: "Amendment No. 1", page: 1, quote: "The Go-Live Date shall be 31 July 2024", source_kind: "matter", structural_ref: "cl. 1" }],
};

describe("SentenceItem", () => {
  it("opens the source page when a citation is clicked", async () => {
    const onOpen = vi.fn();
    render(<ul><SentenceItem s={base} onOpen={onOpen} /></ul>);
    await userEvent.click(screen.getByRole("button", { name: /Open source: Amendment No. 1, p.1/ }));
    expect(onOpen).toHaveBeenCalledWith({ documentId: "d1", title: "Amendment No. 1", page: 1, quote: "The Go-Live Date shall be 31 July 2024" });
  });

  it("strikes through superseded statements and says what replaced them", () => {
    render(<ul><SentenceItem s={{ ...base, state: "SUPERSEDED", superseded_by: "Amendment No. 1, p.1" }} onOpen={vi.fn()} /></ul>);
    expect(screen.getByTestId("sentence")).toHaveClass("SUPERSEDED");
    expect(screen.getByText("Superseded")).toBeInTheDocument();
    expect(screen.getByText("Amendment No. 1, p.1")).toBeInTheDocument();
  });

  it("flags disputed, computed, review and unverified-law statements", () => {
    render(<ul><SentenceItem s={{ ...base, state: "DISPUTED", meta: { needs_review: true, derived: true, verification_status: "UNVERIFIED" } }} onOpen={vi.fn()} /></ul>);
    for (const t of ["Disputed", "Needs review", "Computed", "Unverified text"]) expect(screen.getByText(t)).toBeInTheDocument();
  });

  it("does not make law citations clickable", () => {
    const law: Sentence = { ...base, kind: "authority", citations: [{ document_id: null, document_title: "Indian Contract Act, 1872, s.74", page: null, quote: "x", source_kind: "law" }] };
    render(<ul><SentenceItem s={law} onOpen={vi.fn()} /></ul>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Indian Contract Act, 1872, s.74")).toBeInTheDocument();
  });

  it("marks a cited sentence that failed verification", () => {
    render(<ul><SentenceItem s={{ ...base, status: "UNVERIFIED" }} onOpen={vi.fn()} /></ul>);
    expect(screen.getByText("Unverified")).toBeInTheDocument();
  });

  it("renders nothing for an empty list", () => {
    const { container } = render(<SentenceList items={[]} onOpen={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
