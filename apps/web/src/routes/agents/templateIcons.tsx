import { Bank, Car, DeviceMobile, FirstAid, ShoppingCart, Stethoscope, TrendUp, type Icon } from "@phosphor-icons/react";
import { CarFront, HeartPulse, Landmark, RadioTower, ShoppingBag, type LucideIcon } from "lucide-react";
import type { TemplateCategory } from "../../api/agents";

/** Template icon tokens (templates.icon) to duotone glyphs; unknown tokens fall back to a phone. */
export const TEMPLATE_ICONS: Record<string, Icon> = {
  bank: Bank,
  "trend-up": TrendUp,
  "cell-signal": DeviceMobile,
  "shopping-cart": ShoppingCart,
  stethoscope: Stethoscope,
  car: Car,
  "first-aid": FirstAid,
};

export const CATEGORY_ICONS: Record<TemplateCategory, LucideIcon> = {
  automotive: CarFront,
  banking: Landmark,
  ecommerce: ShoppingBag,
  healthcare: HeartPulse,
  telecom: RadioTower,
};

/** Each category gets one tint from the palette so a grid of templates scans by industry. */
export const CATEGORY_TINT: Record<TemplateCategory, string> = {
  automotive: "bg-warning-soft text-warning-text",
  banking: "bg-accent-soft text-accent-text",
  ecommerce: "bg-danger-soft text-danger-text",
  healthcare: "bg-success-soft text-success-text",
  telecom: "bg-surface-3 text-fg",
};
