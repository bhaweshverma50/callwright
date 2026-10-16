import { FolderOpen, Moon, Plus, Sun, Trash } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { resolvedTheme, setThemePref, useThemePref } from "../../app/theme";
import {
  Badge,
  Button,
  Chip,
  ConfirmDialog,
  CostBreakdownCard,
  Dialog,
  Drawer,
  EmptyState,
  Field,
  IconButton,
  Input,
  Kbd,
  Label,
  Logo,
  MoneyText,
  Pagination,
  Select,
  Skeleton,
  Slider,
  Switch,
  TabPanel,
  Table,
  Tabs,
  Textarea,
  toast,
  type Column,
} from "../../components";
import { referenceBreakdown } from "../public/reference";

const SWATCHES = [
  ["bg", "--bg"],
  ["surface", "--surface"],
  ["surface-2", "--surface-2"],
  ["surface-3", "--surface-3"],
  ["border", "--border"],
  ["text", "--text"],
  ["text-2", "--text-2"],
  ["text-3", "--text-3"],
  ["accent", "--accent"],
  ["accent-soft", "--accent-soft"],
  ["amber", "--amber"],
  ["amber-soft", "--amber-soft"],
  ["danger", "--danger"],
  ["success-soft", "--success-soft"],
] as const;

interface Row {
  id: string;
  agent: string;
  duration: string;
  cost: string;
}
const ROWS: Row[] = [
  { id: "call_01JA8Z3QK0X7", agent: "Front desk", duration: "4:31", cost: "0.477000" },
  { id: "call_01JA8Z4C9M2R", agent: "Billing line", duration: "1:34", cost: "0.110000" },
  { id: "call_01JA8Z5TT6WB", agent: "Front desk", duration: "6:52", cost: "0.731000" },
  { id: "call_01JA8Z6PFJ1D", agent: "After hours", duration: "0:12", cost: "0.015000" },
];
const COLS: Column<Row>[] = [
  { key: "id", header: "Call", cell: (r) => <span className="font-mono text-[12px] text-fg-2">{r.id}</span> },
  { key: "agent", header: "Agent", cell: (r) => r.agent },
  { key: "duration", header: "Duration", numeric: true, cell: (r) => r.duration },
  { key: "cost", header: "Cost", numeric: true, cell: (r) => <MoneyText value={r.cost} places={3} /> },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line py-8">
      <h2 className="mb-5 font-display text-[18px] font-semibold tracking-[-0.01em] text-fg">{title}</h2>
      {children}
    </section>
  );
}

/** Design-system gallery at /dev/components: every primitive, in the current theme. */
export function ComponentsGallery() {
  const pref = useThemePref();
  const theme = resolvedTheme(pref);
  const [select, setSelect] = useState("nova-3");
  const [slider, setSlider] = useState(12_000);
  const [sw, setSw] = useState(true);
  const [tab, setTab] = useState("one");
  const [dialog, setDialog] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [chip, setChip] = useState("100");
  const [page, setPage] = useState(2);

  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-line bg-bg/85 px-6 backdrop-blur-sm">
        <Link to="/" aria-label="Home">
          <Logo />
        </Link>
        <Button
          variant="secondary"
          size="sm"
          icon={theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
          onClick={() => setThemePref(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "Light" : "Dark"} theme
        </Button>
      </header>
      <main className="mx-auto max-w-[1100px] px-6 pb-24 pt-10">
        <h1 className="font-display text-[30px] font-semibold tracking-[-0.025em] text-fg">Components</h1>
        <p className="mt-2 max-w-[70ch] text-[13.5px] text-fg-2">
          Callwright design system. Cool grey-blue neutrals, a signal teal for action, focus and live state, amber for evidence and
          warnings. Bricolage Grotesque for display, IBM Plex Sans for UI, IBM Plex Mono for numbers and labels.
        </p>

        <Section title="Tokens">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {SWATCHES.map(([name, v]) => (
              <div key={name} className="flex flex-col gap-1.5">
                <span className="h-12 rounded-control border border-line" style={{ background: `var(${v})` }} />
                <span className="font-mono text-[11px] text-fg-2">{name}</span>
              </div>
            ))}
          </div>
          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <p className="font-display text-[28px] font-semibold tracking-[-0.025em] text-fg">Display 28</p>
            <p className="text-[14px] text-fg">IBM Plex Sans 14 for interface and body text.</p>
            <p className="font-mono text-[13px] text-fg tnum">$1,234.567 / 0.0085</p>
          </div>
        </Section>

        <Section title="Buttons">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" icon={<Plus aria-hidden />}>
              Create agent
            </Button>
            <Button>Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger" icon={<Trash aria-hidden />}>
              Delete
            </Button>
            <Button variant="link">Link</Button>
            <Button variant="primary" pending>
              Saving
            </Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button size="sm">Small</Button>
            <Button size="lg" variant="primary">
              Large
            </Button>
            <IconButton label="Open folder">
              <FolderOpen className="size-4" aria-hidden />
            </IconButton>
          </div>
        </Section>

        <Section title="Inputs">
          <div className="grid gap-5 sm:grid-cols-3">
            <Field label="Workspace name" hint="Shown in the top bar.">
              {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} defaultValue="Halcyon Dental Group" />}
            </Field>
            <Field label="Amount" error="The minimum top-up is $5.">
              {({ id, describedBy, invalid }) => <Input id={id} prefix="$" className="font-mono" aria-describedby={describedBy} aria-invalid={invalid} defaultValue="4" />}
            </Field>
            <Field label="Disabled">
              {({ id }) => <Input id={id} disabled defaultValue="Read only" />}
            </Field>
            <Field label="Speech to text" className="sm:col-span-1">
              {({ id }) => (
                <Select
                  id={id}
                  value={select}
                  onValueChange={setSelect}
                  groups={[
                    {
                      label: "Deepgram",
                      options: [
                        { value: "nova-3", label: "Nova-3", meta: "$0.0085/m" },
                        { value: "nova-2", label: "Nova-2", meta: "$0.0058/m" },
                      ],
                    },
                    { label: "AssemblyAI", options: [{ value: "us", label: "Universal Streaming", meta: "$0.0030/m" }] },
                  ]}
                />
              )}
            </Field>
            <Field label="Greeting" className="sm:col-span-2">
              {({ id }) => <Textarea id={id} defaultValue="Thanks for calling Halcyon Dental, this is Mira. How can I help?" />}
            </Field>
          </div>
          <div className="mt-6 grid gap-6 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label>Slider {slider.toLocaleString()}</Label>
              <Slider aria-label="Tokens" value={slider} min={0} max={80_000} step={1_000} onValueChange={setSlider} />
            </div>
            <Switch checked={sw} onCheckedChange={setSw} label="Record calls by default" description="Agents can override this." />
          </div>
        </Section>

        <Section title="Badges and chips">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>Draft</Badge>
            <Badge tone="accent">Live</Badge>
            <Badge tone="success">Passed</Badge>
            <Badge tone="amber">Surcharge</Badge>
            <Badge tone="danger">Failed</Badge>
            <span className="mx-2 h-5 w-px bg-line" />
            {["25", "100", "500"].map((v) => (
              <Chip key={v} selected={chip === v} onClick={() => setChip(v)}>
                ${v}
              </Chip>
            ))}
            <span className="mx-2 h-5 w-px bg-line" />
            <Kbd>[</Kbd>
            <span className="text-[12.5px] text-fg-3">toggles the rail</span>
          </div>
          <div className="mt-5 flex flex-wrap items-baseline gap-6">
            <MoneyText value="1234.567891" places={3} className="text-[22px] text-fg" />
            <MoneyText value="25.000000" places={3} signed toned />
            <MoneyText value="-0.477000" places={3} signed toned />
          </div>
        </Section>

        <Section title="Tabs">
          <Tabs
            value={tab}
            onValueChange={setTab}
            items={[
              { value: "one", label: "Transactions", count: 312 },
              { value: "two", label: "Usage" },
              { value: "three", label: "Invoices", disabled: true },
            ]}
          >
            <TabPanel value="one">
              <p className="text-[13px] text-fg-2">Arrow keys move between tabs.</p>
            </TabPanel>
            <TabPanel value="two">
              <p className="text-[13px] text-fg-2">Second panel.</p>
            </TabPanel>
          </Tabs>
        </Section>

        <Section title="Table and pagination">
          <div className="rounded-panel border border-line bg-surface">
            <Table columns={COLS} rows={ROWS} rowKey={(r) => r.id} caption="Sample calls" />
            <div className="border-t border-line">
              <Pagination page={page} totalPages={16} total={312} pageSize={20} onPageChange={setPage} noun="calls" />
            </div>
          </div>
          <div className="mt-4 rounded-panel border border-line bg-surface">
            <Table columns={COLS} rows={undefined} rowKey={(r) => r.id} loading skeletonRows={3} caption="Loading" />
          </div>
        </Section>

        <Section title="Overlays and feedback">
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setDialog(true)}>Open dialog</Button>
            <Button onClick={() => setConfirm(true)}>Confirm dialog</Button>
            <Button onClick={() => setDrawer(true)}>Open drawer</Button>
            <Button onClick={() => toast({ tone: "success", title: "Settings saved" })}>Success toast</Button>
            <Button onClick={() => toast({ tone: "error", title: "Could not save", description: "Something went wrong on our side. Reference 4f1c9e0a." })}>
              Error toast
            </Button>
          </div>
          <Dialog
            open={dialog}
            onOpenChange={setDialog}
            title="Rename agent"
            description="The name shows in call lists and reports."
            footer={
              <>
                <Button onClick={() => setDialog(false)}>Cancel</Button>
                <Button variant="primary" onClick={() => setDialog(false)}>
                  Save
                </Button>
              </>
            }
          >
            <Field label="Name">{({ id }) => <Input id={id} defaultValue="Front desk" />}</Field>
          </Dialog>
          <ConfirmDialog
            open={confirm}
            onOpenChange={setConfirm}
            title="Leave without saving?"
            description="You have changes that are not saved."
            confirmLabel="Leave"
            cancelLabel="Stay"
            tone="danger"
            onConfirm={() => setConfirm(false)}
          />
          <Drawer open={drawer} onOpenChange={setDrawer} title="Call with +1 (312) 847-1928" meta="call_01JA8Z3QK0X7 / Oct 14, 10:42">
            <CostBreakdownCard breakdown={referenceBreakdown} />
          </Drawer>
        </Section>

        <Section title="Empty and loading states">
          <div className="grid gap-5 md:grid-cols-2">
            <div className="rounded-panel border border-dashed border-line-strong px-5">
              <EmptyState
                icon={<FolderOpen />}
                title="No datasets yet"
                actions={
                  <Button variant="primary" size="sm" icon={<Plus aria-hidden />}>
                    New dataset
                  </Button>
                }
              >
                Save calls into a dataset to replay them against a new prompt.
              </EmptyState>
            </div>
            <div className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-5">
              <Skeleton className="h-5 w-1/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
        </Section>

        <Section title="Cost breakdown">
          <div className="max-w-[460px]">
            <CostBreakdownCard breakdown={referenceBreakdown} />
          </div>
        </Section>
      </main>
    </div>
  );
}
