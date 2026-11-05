import { Compass, LogOut, Monitor, Moon, Settings, Sun } from "lucide-react";
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
  TruncatedText,
  cn,
  focusRing,
} from "../components";
import { signOut } from "./auth";
import { setThemePref, useThemePref, type ThemePref } from "./theme";
import { useTour } from "./tour/context";

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
  const tour = useTour();

  return (
    <Menu>
      <MenuTrigger
        aria-label={email ? `Account menu for ${email}` : "Account menu"}
        className={cn(
          "flex cursor-pointer items-center gap-2 rounded-full py-0.5 pl-0.5 pr-0.5 transition-colors hover:bg-surface-3 lg:pr-2.5",
          focusRing,
        )}
      >
        <span className="bg-accent grid size-8 place-items-center rounded-full text-[12px] font-semibold text-white">
          {email ? initialsOf(email) : ""}
        </span>
        {email ? (
          <TruncatedText focusable={false} side="bottom" className="hidden max-w-[200px] text-[13px] text-fg-2 lg:block">
            {email}
          </TruncatedText>
        ) : (
          <Skeleton className="hidden h-3 w-28 lg:block" />
        )}
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>
          <TruncatedText focusable={false} side="left" className="text-[13px] font-medium text-fg">
            {email}
          </TruncatedText>
          <TruncatedText focusable={false} side="left" className="text-[12px] text-fg-3">
            {me?.workspace.name}
          </TruncatedText>
        </MenuLabel>
        <MenuSeparator />
        <MenuItem onSelect={() => navigate("/settings")}>
          <Settings aria-hidden />
          Settings
        </MenuItem>
        {tour && (
          <MenuItem onSelect={tour.start}>
            <Compass aria-hidden />
            Guided setup
          </MenuItem>
        )}
        <MenuSeparator />
        <p className="px-2 pb-1 pt-1.5 text-[12px] font-medium text-fg-3">Theme</p>
        <MenuRadioGroup value={theme} onValueChange={(v) => setThemePref(v as ThemePref)}>
          <MenuRadioItem value="system">
            <Monitor aria-hidden /> System
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
          <LogOut aria-hidden />
          Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
