import type { Session, ViewerTarget } from "../types";

export interface ViewProps {
  matterId: string;
  asOf: number;
  latest: number;
  today: string;
  session: Session;
  onOpen: (t: ViewerTarget) => void;
  onChanged: () => void;
}
export const canWrite = (s: Session) => s.role !== "viewer";
