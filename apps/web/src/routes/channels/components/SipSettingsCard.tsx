import { ArrowDownToLine, Network, Server } from "lucide-react";
import { CopyButton, Panel, Skeleton } from "../../../components";
import { useSipSettings } from "../../../api/channels";

function AddressRow({ icon, label, value, help }: { icon: React.ReactNode; label: string; value: string; help: string }) {
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <div className="flex items-center gap-2 text-[13px] font-medium text-fg-2 [&_svg]:size-3.5 [&_svg]:text-fg-3">
        {icon}
        {label}
      </div>
      <div className="group flex items-center gap-2 rounded-control border border-line bg-surface-2/70 py-1 pl-3 pr-1 transition-colors hover:border-accent/40">
        <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg" title={value}>
          {value}
        </code>
        <CopyButton value={value} label={`Copy ${label.toLowerCase()}`} />
      </div>
      <p className="text-[12px] leading-relaxed text-fg-3">{help}</p>
    </div>
  );
}

/** Where operators point their carrier (010 T022, FR-005, research R3). */
export function SipSettingsCard() {
  const sip = useSipSettings();
  return (
    <Panel
      title="Point your carrier here"
      description="Set these at your SIP trunk provider so calls reach your agents."
      icon={<Network />}
      bodyClassName="p-0"
    >
      {sip.isPending ? (
        <div className="flex flex-col gap-3 p-5">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : sip.data && !sip.data.telephony_enabled ? (
        <div className="flex flex-col gap-3 px-5 py-4">
          {["Origination address", "Direct address"].map((label) => (
            <div key={label} className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-fg-2">{label}</span>
              <div className="flex h-9 items-center rounded-control border border-dashed border-line-strong bg-surface-2/50 px-3 text-[13px] text-fg-3">
                Shown once telephony is switched on
              </div>
            </div>
          ))}
          <p className="text-[12px] leading-relaxed text-fg-3">
            Import numbers now; you point your carrier at Callwright when the SIP service is enabled.
          </p>
        </div>
      ) : sip.data ? (
        <div className="divide-y divide-line">
          <AddressRow
            icon={<ArrowDownToLine aria-hidden />}
            label="Origination address"
            value={sip.data.origination_uri}
            help="Your trunk's inbound (origination) URI. Calls to any imported number arrive here."
          />
          <AddressRow
            icon={<Server aria-hidden />}
            label="Direct address"
            value={sip.data.direct_uri_template}
            help="Dial a single number directly, with {e164} replaced by the number."
          />
          <div className="flex flex-wrap items-center gap-1.5 px-5 py-3.5">
            <span className="mr-1 text-[13px] text-fg-3">Transports</span>
            {sip.data.transports.map((t) => (
              <span key={t} className="rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-[12px] uppercase text-fg-2">
                {t}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="p-5 text-[13px] text-fg-3">SIP settings did not load.</p>
      )}
    </Panel>
  );
}
