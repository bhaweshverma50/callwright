import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SummaryText } from "./SummaryText";

describe("call summary", () => {
  it("shows the first line as a sentence and labelled lines as a list", () => {
    render(<SummaryText text={"Jordan agreed to pay on Friday.\nDetails: $240, reference LN-2231.\nNext step: payment link by SMS."} />);
    expect(screen.getByText("Jordan agreed to pay on Friday.")).toBeInTheDocument();
    expect(screen.getByText("Details").tagName).toBe("DT");
    expect(screen.getByText("$240, reference LN-2231").tagName).toBe("DD");
    expect(screen.getByText("Next step")).toBeInTheDocument();
  });

  it("splits inline labels and drops transcript line references", () => {
    render(<SummaryText text={"The caller paid. Details: name Bhavesh Verma [3]. Actions: sent a link [6-8]."} />);
    expect(screen.getByText("The caller paid.")).toBeInTheDocument();
    expect(screen.getByText("Name Bhavesh Verma")).toBeInTheDocument();
    expect(screen.getByText("Sent a link")).toBeInTheDocument();
  });

  it("lists semicolon-separated details as bullets", () => {
    render(<SummaryText text={"Jordan agreed to pay.\nDetails: name Jordan Lee; $240 due; reference LN-2231."} />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Name Jordan Lee", "$240 due", "Reference LN-2231"]);
  });
});
