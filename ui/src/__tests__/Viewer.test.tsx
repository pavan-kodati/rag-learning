import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { Viewer } from "../components/Viewer";

const page = { document_id: "d1", title: "MSA", page: 1, total_pages: 3, text: "page text", width: 600, height: 800, extraction_method: "DIGITAL", ocr_confidence: null, facts: [{ assertion_id: "a", assertion_text: "A fact", source_quote: "q", state: "ACTIVE" }] };

describe("Viewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the page image and highlights the cited quote at the right place", async () => {
    vi.spyOn(api, "page").mockResolvedValue(page);
    vi.spyOn(api, "highlight").mockResolvedValue({ width: 600, height: 800, found: true, rects: [{ page: 1, x0: 60, y0: 80, x1: 300, y1: 100 }] });
    render(<Viewer target={{ documentId: "d1", title: "MSA", page: 1, quote: "on or before 30 June 2024" }} onClose={vi.fn()} />);
    expect(await screen.findByAltText("MSA, page 1")).toBeInTheDocument();
    const hl = await screen.findByTestId("highlight");
    expect(hl.style.left).toBe("10%");
    expect(hl.style.top).toBe("10%");
    expect(hl.style.width).toBe("40%");
    expect(screen.getByText(/on or before 30 June 2024/)).toBeInTheDocument();
    expect(screen.getByText(/Facts recorded from this page/)).toBeInTheDocument();
  });

  it("says so when the quote cannot be located, but still shows the page", async () => {
    vi.spyOn(api, "page").mockResolvedValue(page);
    vi.spyOn(api, "highlight").mockResolvedValue({ width: 600, height: 800, found: false, rects: [] });
    render(<Viewer target={{ documentId: "d1", title: "MSA", page: 1, quote: "something" }} onClose={vi.fn()} />);
    expect(await screen.findByText(/could not be located exactly/)).toBeInTheDocument();
    expect(screen.queryByTestId("highlight")).toBeNull();
  });

  it("shows an error when the page cannot be loaded", async () => {
    vi.spyOn(api, "page").mockRejectedValue(new Error("page 9 not found"));
    render(<Viewer target={{ documentId: "d1", title: "MSA", page: 9 }} onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("page 9 not found");
  });

  it("pages forwards and back, and closes with the keyboard", async () => {
    const pageSpy = vi.spyOn(api, "page").mockResolvedValue(page);
    vi.spyOn(api, "highlight").mockResolvedValue({ width: 600, height: 800, found: false, rects: [] });
    const onClose = vi.fn();
    render(<Viewer target={{ documentId: "d1", title: "MSA", page: 1 }} onClose={onClose} />);
    await screen.findByAltText("MSA, page 1");
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Next page"));
    await waitFor(() => expect(pageSpy).toHaveBeenLastCalledWith("d1", 2));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("mentions OCR confidence on scanned pages", async () => {
    vi.spyOn(api, "page").mockResolvedValue({ ...page, extraction_method: "OCR", ocr_confidence: 71.2 });
    render(<Viewer target={{ documentId: "d1", title: "Scan", page: 1 }} onClose={vi.fn()} />);
    expect(await screen.findByText(/scanned page \(OCR 71%\)/)).toBeInTheDocument();
  });
});
