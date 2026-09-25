import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the research workflow at the root route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /ask one research question/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start research/i })).toBeInTheDocument();
  });
});
