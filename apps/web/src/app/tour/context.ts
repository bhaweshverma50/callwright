import { createContext, useContext } from "react";
import type { TourState } from "./machine";

export interface TourApi {
  state: TourState;
  /** Start (or restart) from the first step. */
  start: () => void;
  resume: () => void;
  skip: () => void;
}

export const TourContext = createContext<TourApi | null>(null);

/** The guided setup tour, for the account menu and anything else that starts it. */
export function useTour(): TourApi | null {
  return useContext(TourContext);
}
