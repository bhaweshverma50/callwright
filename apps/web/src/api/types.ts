/** Friendly aliases over the generated contract types (src/api/schema.d.ts). */
import type { components, paths } from "./schema";

export type { paths, components };
type S = components["schemas"];

type Method = "get" | "post" | "put" | "patch" | "delete";
type JsonBody<R> = R extends { content: { "application/json": infer B } } ? B : never;
type Success<Rs> = JsonBody<Rs[Extract<keyof Rs, 200 | 201 | 202>]>;

/** The JSON body an operation answers with on success, for responses the contract does not name. */
export type ResponseOf<P extends keyof paths, M extends Method> = paths[P][M] extends { responses: infer Rs } ? Success<Rs> : never;
/** The query parameters an operation accepts. */
export type QueryOf<P extends keyof paths, M extends Method> = paths[P][M] extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;
/** The JSON request body an operation accepts. */
export type BodyOf<P extends keyof paths, M extends Method> = paths[P][M] extends { requestBody?: infer B } ? JsonBody<NonNullable<B>> : never;

export type Problem = S["Problem"];
export type FieldError = S["FieldError"];
export type MoneyUsd = S["MoneyUsd"];
export type PageMeta = S["PageMeta"];

export type Session = S["Session"];
export type RegisteredSession = S["RegisteredSession"];
export type Me = S["Me"];
export type User = S["User"];
export type Workspace = S["Workspace"];
export type Preferences = S["Preferences"];
export type Onboarding = S["Onboarding"];
export type OnboardingStatus = S["OnboardingStatus"];
export type PreferencesUpdate = S["PreferencesUpdate"];

export type TransactionType = S["TransactionType"];
export type Transaction = S["Transaction"];
export type TransactionPage = PageMeta & { items: Transaction[] };
export type Balance = paths["/billing/balance"]["get"]["responses"]["200"]["content"]["application/json"];
export type CheckoutSession = paths["/billing/checkout-sessions"]["post"]["responses"]["201"]["content"]["application/json"];

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
