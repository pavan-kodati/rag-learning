import { describe, expect, it } from "vitest";
import { fmtDate, titleCase } from "../format";

describe("format", () => {
  it("formats ISO dates in the Indian day-first style", () => { expect(fmtDate("2025-10-10")).toMatch(/10 Oct 2025/); });
  it("tolerates empty and invalid dates", () => { expect(fmtDate(null)).toBe(""); expect(fmtDate("nonsense")).toBe("nonsense"); });
  it("title-cases enum words", () => { expect(titleCase("NO_DATE")).toBe("No date"); });
});
