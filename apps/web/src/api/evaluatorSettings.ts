/**
 * Check settings forms are generated from each evaluator's `settings_schema` (007 FR-038, R15).
 * The same rules run in the editor (Save stays disabled while a field is invalid) and in the
 * mock API; the platform validates again on save.
 */
import type { JudgeModel, SettingsField } from "./quality";

export const fmtNumber = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 4 });

export function schemaFields(schema: Record<string, unknown> | undefined): SettingsField[] {
  const fields = schema?.fields;
  return Array.isArray(fields) ? fields : [];
}

/** Helper text with `{default}` replaced by the field default, so it can never disagree. */
export function helperText(field: SettingsField, models?: JudgeModel[]): string | undefined {
  if (!field.helper) return undefined;
  return field.helper.replace(/\{default\}/g, () => displayValue(field, field.default, models));
}

export function displayValue(field: SettingsField, value: unknown, models?: JudgeModel[]): string {
  if (value === null || value === undefined || value === "") return "none";
  if (typeof value === "number") return fmtNumber(value);
  if (typeof value === "boolean") return value ? "on" : "off";
  if (field.options_source === "judge_models") return models?.find((m) => m.model_id === value)?.display_name ?? String(value);
  return String(value);
}

/** Options of a select, with judge models filled from the platform list when the schema says so. */
export function optionsFor(field: SettingsField, models?: JudgeModel[]): string[] {
  if (field.options_source === "judge_models" && models?.length) return models.map((m) => m.model_id);
  return field.options ?? [];
}

function rangeText(field: SettingsField): string {
  if (field.min !== undefined && field.max !== undefined) return `from ${fmtNumber(field.min)} to ${fmtNumber(field.max)}`;
  if (field.min !== undefined) return `of at least ${fmtNumber(field.min)}`;
  if (field.max !== undefined) return `of at most ${fmtNumber(field.max)}`;
  return "";
}

/**
 * Error for one field value (as typed or as sent), or null when valid. Integer fields reject
 * decimals; selects reject anything not in their options.
 */
export function fieldError(field: SettingsField, value: unknown, models?: JudgeModel[]): string | null {
  if (field.type === "int" || field.type === "number") {
    const msg = `Enter a ${field.type === "int" ? "whole number" : "number"} ${rangeText(field)}`.trim();
    const n = typeof value === "number" ? value : typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
    if (!Number.isFinite(n)) return msg;
    if (field.type === "int" && !Number.isInteger(n)) return msg;
    if (field.min !== undefined && n < field.min) return msg;
    if (field.max !== undefined && n > field.max) return msg;
    return null;
  }
  if (field.type === "select") {
    const options = optionsFor(field, models);
    if (options.length && !options.includes(String(value))) {
      return field.options_source === "judge_models" ? "Choose one of the listed judge models" : "Choose one of the options";
    }
    return null;
  }
  if (field.type === "bool") return typeof value === "boolean" ? null : "Choose on or off";
  return null;
}

/** A typed value from the form's text for numeric fields. */
export function parseFieldValue(field: SettingsField, text: string): unknown {
  if (field.type === "int" || field.type === "number") {
    // Only text that reads back the same becomes a number, so "2." or "-" stay as typed.
    const n = Number(text);
    return text.trim() !== "" && Number.isFinite(n) && String(n) === text.trim() ? n : text;
  }
  return text;
}
