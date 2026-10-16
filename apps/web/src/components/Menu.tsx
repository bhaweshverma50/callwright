import * as DM from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import { cn } from "./cn";

export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;

export function MenuContent({ children, align = "end", className }: { children: ReactNode; align?: "start" | "end"; className?: string }) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn("z-50 min-w-[232px] rounded-panel border border-line bg-surface p-1.5 shadow-pop data-[state=open]:animate-pop-in data-[state=closed]:animate-[pop-in_120ms_ease-in_reverse]", className)}
      >
        {children}
      </DM.Content>
    </DM.Portal>
  );
}

const itemClass =
  "flex h-9 cursor-pointer select-none items-center gap-2.5 rounded-[6px] px-2 text-[13px] text-fg outline-none transition-colors data-[highlighted]:bg-accent-soft/60 [&_svg]:size-4 [&_svg]:text-fg-2";

export function MenuItem({ children, onSelect, danger }: { children: ReactNode; onSelect?: () => void; danger?: boolean }) {
  return (
    <DM.Item onSelect={onSelect} className={cn(itemClass, danger && "text-danger-text [&_svg]:text-danger-text")}>
      {children}
    </DM.Item>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <DM.Label className="px-2 pb-1.5 pt-1.5">{children}</DM.Label>;
}

export function MenuSeparator() {
  return <DM.Separator className="-mx-1 my-1 h-px bg-line" />;
}

export const MenuRadioGroup = DM.RadioGroup;

export function MenuRadioItem({ value, children }: { value: string; children: ReactNode }) {
  return (
    <DM.RadioItem value={value} className={cn(itemClass, "data-[state=checked]:text-accent-text data-[state=checked]:[&_svg]:text-accent-text")}>
      {children}
    </DM.RadioItem>
  );
}
