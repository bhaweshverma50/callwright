import type { ReactNode } from "react";

function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-[720px] px-4 pb-24 pt-12 sm:px-6 lg:pt-16">
      <h1 className="font-display text-[30px] font-semibold tracking-[-0.03em] text-fg sm:text-[38px]">{title}</h1>
      <p className="mt-3 text-[13px] text-fg-3">Last updated {updated}</p>
      <div className="mt-10 flex flex-col gap-9 border-t border-line pt-10 text-[15.5px] leading-[1.75] text-fg-2 [&_h2]:mb-2.5 [&_h2]:font-display [&_h2]:text-[17px] [&_h2]:font-medium [&_h2]:tracking-[-0.01em] [&_h2]:text-fg [&_li]:ml-5 [&_li]:list-disc [&_li]:marker:text-accent [&_ul]:flex [&_ul]:flex-col [&_ul]:gap-1.5">
        {children}
      </div>
    </article>
  );
}

/** Privacy policy (T044, FR-016). Plain-language summary of how call data is handled. */
export function Privacy() {
  return (
    <LegalPage title="Privacy policy" updated="16 October 2026">
      <section>
        <h2>What we collect</h2>
        <p>
          Your account email and password hash, your workspace settings, and the data your agents produce: call recordings, transcripts, call
          metadata, evaluator results and usage records used for billing.
        </p>
      </section>
      <section>
        <h2>How call data is protected</h2>
        <ul>
          <li>Every record belongs to one workspace, and access is enforced in the database, not only in the application.</li>
          <li>Recordings and transcripts are encrypted at rest and served through short-lived signed links.</li>
          <li>API keys, SIP credentials and webhook secrets are stored encrypted and never shown in full again.</li>
        </ul>
      </section>
      <section>
        <h2>Recording</h2>
        <p>
          Each workspace chooses whether calls are recorded by default, and agents can override it. You are responsible for telling callers when a
          call is recorded where the law requires it.
        </p>
      </section>
      <section>
        <h2>Vendors</h2>
        <p>
          Speech recognition, language model, voice and payment providers process call content or payment details only to perform the service you
          selected for each agent.
        </p>
      </section>
      <section>
        <h2>Retention and deletion</h2>
        <p>Call data is kept for your workspace's retention period, then deleted. Ask us to delete your account at any time.</p>
      </section>
    </LegalPage>
  );
}

/** Terms of service (T044, FR-016). */
export function Terms() {
  return (
    <LegalPage title="Terms of service" updated="16 October 2026">
      <section>
        <h2>Accounts</h2>
        <p>One account owns one workspace. Keep your password private; you are responsible for activity in your workspace.</p>
      </section>
      <section>
        <h2>Credit and billing</h2>
        <ul>
          <li>Usage is paid from a prepaid balance in US dollars. Top-ups range from $5 to $10,000.</li>
          <li>Calls are billed per second, rounded up, at the catalog rates in effect when each call starts.</li>
          <li>New calls are refused when the balance reaches zero. A call in progress may finish within a small grace amount.</li>
          <li>Refunds and disputes appear as separate adjustments; past transactions are never edited.</li>
        </ul>
      </section>
      <section>
        <h2>Acceptable use</h2>
        <p>
          Do not use Callwright for unlawful calling, to deceive callers about who they are talking to, or to call numbers that asked not to be
          contacted.
        </p>
      </section>
      <section>
        <h2>Changes</h2>
        <p>We publish rate changes as a new catalog version before they take effect. Calls already made keep their original rates.</p>
      </section>
    </LegalPage>
  );
}
