import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setSession } from "../api";
import { Login } from "../components/Login";
import { NewMatter } from "../components/NewMatter";

afterEach(() => { vi.restoreAllMocks(); setSession(null); window.localStorage.clear(); });

describe("Login", () => {
  it("shows the server's message on bad credentials and does not sign in", async () => {
    vi.spyOn(api, "login").mockRejectedValue(new ApiError(401, { code: "unauthorized", detail: "invalid credentials" }));
    const onDone = vi.fn();
    render(<Login onDone={onDone} />);
    await userEvent.type(screen.getByLabelText("Username"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid credentials");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("stores the session and continues on success", async () => {
    vi.spyOn(api, "login").mockResolvedValue({ access_token: "tok", username: "lawyer", role: "analyst" });
    const onDone = vi.fn();
    render(<Login onDone={onDone} />);
    await userEvent.type(screen.getByLabelText("Username"), "lawyer");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ username: "lawyer", role: "analyst", token: "tok" }));
    expect(JSON.parse(window.localStorage.getItem("lw.session") as string).token).toBe("tok");
  });

  it("disables the button until both fields are filled", async () => {
    render(<Login onDone={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });
});

describe("NewMatter", () => {
  it("creates a matter with only the filled-in parties", async () => {
    const create = vi.spyOn(api, "createMatter").mockResolvedValue({ matter_id: "m1" } as any);
    const onCreated = vi.fn();
    render(<NewMatter onClose={vi.fn()} onCreated={onCreated} />);
    await userEvent.type(screen.getByLabelText("Case number"), "CS(COMM) 1/2025");
    await userEvent.type(screen.getByLabelText("Title"), "A v B");
    await userEvent.type(screen.getByLabelText("Party 1 name"), "Alpha Ltd");
    await userEvent.click(screen.getByRole("button", { name: "Create matter" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({ matter_number: "CS(COMM) 1/2025", title: "A v B", matter_type: "PAYMENT_RECOVERY", forum: undefined, parties: [{ name: "Alpha Ltd", role: "PLAINTIFF" }] });
  });

  it("keeps the dialog open and explains a duplicate case number", async () => {
    vi.spyOn(api, "createMatter").mockRejectedValue(new ApiError(409, { code: "conflict", detail: "a matter numbered 'X' already exists", errors: [{ field: "matter_number", message: "already exists" }] }));
    const onCreated = vi.fn();
    render(<NewMatter onClose={vi.fn()} onCreated={onCreated} />);
    await userEvent.type(screen.getByLabelText("Case number"), "X");
    await userEvent.type(screen.getByLabelText("Title"), "t");
    await userEvent.click(screen.getByRole("button", { name: "Create matter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    expect(screen.getByText("already exists", { selector: ".err" })).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("cannot be submitted without a number and title, and closes with Escape", async () => {
    const onClose = vi.fn();
    render(<NewMatter onClose={onClose} onCreated={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Create matter" })).toBeDisabled();
    screen.getByRole("dialog").focus();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });
});
