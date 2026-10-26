import { describe, expect, it } from "vitest";
import { categoryNameError, e164Error, fieldNameError, jsonError, maxRoundsError, timeoutError, toVariableName, urlError } from "./fieldRules";

describe("node field rules (T104)", () => {
  it("checks max rounds 1 to 20", () => {
    expect(maxRoundsError(5)).toBeNull();
    expect(maxRoundsError(0)).toMatch(/1 to 20/);
    expect(maxRoundsError(25)).toMatch(/1 to 20/);
    expect(maxRoundsError(2.5)).toMatch(/whole number/);
  });

  it("checks international numbers", () => {
    expect(e164Error("+14155550100")).toBeNull();
    expect(e164Error("12345")).toMatch(/\+14155550100/);
  });

  it("wants absolute https URLs", () => {
    expect(urlError("https://api.example.com/orders/{{id}}")).toBeNull();
    expect(urlError("notaurl")).toMatch(/full URL/);
    expect(urlError("http://api.example.com")).toMatch(/https/);
  });

  it("reports JSON errors with the line", () => {
    expect(jsonError('{"a": 1}')).toBeNull();
    expect(jsonError('{"name": "{{name}}"}')).toBeNull();
    expect(jsonError('{\n  "a": 1,\n  "b": \n}')).toMatch(/^Line \d+:/);
    expect(jsonError("", { required: true })).toBe("Enter JSON.");
  });

  it("checks timeouts and names", () => {
    expect(timeoutError(8000)).toBeNull();
    expect(timeoutError(60000)).toMatch(/1 to 30 seconds/);
    expect(categoryNameError("sales", ["Sales"])).toMatch(/already/);
    expect(categoryNameError("!x", [])).toMatch(/letters/);
    expect(fieldNameError("Bad Name", [])).toMatch(/lowercase/);
    expect(toVariableName("Customer Name")).toBe("customer_name");
    expect(toVariableName(" 2nd Phone! ")).toBe("v_2nd_phone");
  });
});
