import { Desktop, GearSix, Moon, SignOut, Sun } from "@phosphor-icons/react";
import { useNavigate } from "react-router";
import { useMe } from "../api/queries";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
  Skeleton,
  cn,
  focusRing,
} from "../components";
import { signOut } from "./auth";
import { setThemePref, useThemePref, type ThemePref } from "./theme";

export function initialsOf(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._+-]+/).filter(Boolean);
  const letters = parts.length >= 2 ? `${parts[0]![0]}${parts[1]![0]}` : local.slice(0, 2);
  return letters.toUpperCase() || "?";
}

/** Avatar initials, email, theme, Settings and Sign out (T042, T093, US1.5). */
export function UserMenu() {
  const { data: me } = useMe();
  const navigate = useNavigate();
  const theme = useThemePref();
  const email = me?.user.email;

  return (
    <Menu>
      <MenuTrigger
        aria-label={email ? `Account menu for ${email}` : "Account menu"}
        className={cn("flex items-center gap-2 rounded-full py-0.5 pl-0.5 pr-2 hover:bg-surface-3", focusRing)}
      >
        <span className="grid size-7 place-items-center rounded-full bg-accent-soft font-mono text-[11px] font-semibold text-accent-text">
          {email ? initialsOf(email) : ""}
        </span>
        <span className="hidden max-w-[200px] truncate text-[12.5px] text-fg-2 lg:inline">
          {email ?? <Skeleton className="h-3 w-28" />}
        </span>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>
          <span className="block truncate text-[13px] font-medium text-fg">{email}</span>
          <span className="block truncate text-[12px] text-fg-3">{me?.workspace.name}</span>
        </MenuLabel>
        <MenuSeparator />
        <MenuItem onSelect={() => navigate("/settings")}>
          <GearSix aria-hidden />
          Settings
        </MenuItem>
        <MenuSeparator />
        <p className="px-2 pb-1 pt-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-fg-3">Theme</p>
        <MenuRadioGroup value={theme} onValueChange={(v) => setThemePref(v as ThemePref)}>
          <MenuRadioItem value="system">
            <Desktop aria-hidden /> System
          </MenuRadioItem>
          <MenuRadioItem value="light">
            <Sun aria-hidden /> Light
          </MenuRadioItem>
          <MenuRadioItem value="dark">
            <Moon aria-hidden /> Dark
          </MenuRadioItem>
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuItem
          onSelect={async () => {
            await signOut();
            navigate("/login", { replace: true });
          }}
        >
          <SignOut aria-hidden />
          Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
