export function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const MATTER_TYPES: Record<string, string> = {
  BREACH: "Breach / non-performance",
  PAYMENT_RECOVERY: "Payment / recovery",
  TERMINATION_INJUNCTION: "Termination / injunction",
};

export function titleCase(s: string): string {
  return s.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function download(filename: string, text: string, mime = "text/markdown"): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
