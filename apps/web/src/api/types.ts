/** Friendly aliases over the generated contract types (src/api/schema.d.ts). */
import type { components, paths } from "./schema";

export type { paths, components };
type S = components["schemas"];

export type Problem = S["Problem"];
export type FieldError = S["FieldError"];
export type MoneyUsd = S["MoneyUsd"];
export type PageMeta = S["PageMeta"];

export type Session = S["Session"];
export type Me = S["Me"];
export type User = S["User"];
export type Workspace = S["Workspace"];

export type TransactionType = S["TransactionType"];
export type Transaction = S["Transaction"];
export type TransactionPage = PageMeta & { items: Transaction[] };
export type Balance = paths["/billing/balance"]["get"]["responses"]["200"]["content"]["application/json"];
export type CheckoutSession =
  paths["/billing/checkout-sessions"]["post"]["responses"]["201"]["content"]["application/json"];

export type Catalog = S["Catalog"];
export type CatalogEntry = S["CatalogEntry"];
export type PricingComponent = S["Component"];
export type QuoteRequest = S["QuoteRequest"];
export type Quote = S["Quote"];
export type QuoteLine = S["QuoteLine"];
export type CostBreakdown = S["CostBreakdown"];
export type CostLine = S["CostLine"];

export type UsageReport = S["UsageReport"];
export type UsageRow = S["UsageRow"];
export type FeatureFamily = S["FeatureFamily"];
