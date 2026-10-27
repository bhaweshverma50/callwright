import { BatteryLow, Landmark, Stethoscope, type LucideIcon } from "lucide-react";

/**
 * The home page playground's scenarios. Keys match the API's DEMO_AGENTS keys; each one is a
 * published agent in the demo workspace made from the template named here. The visitor gets a
 * part to play, so they know what to say when the agent picks up.
 */
export interface Scenario {
  key: string;
  label: string;
  icon: LucideIcon;
  /** Seed template the demo agent is made from (services/api/app/templates/seed). */
  template: string;
  action: string;
  brief: string;
  lines: [string, string];
}

export const SCENARIOS: Scenario[] = [
  {
    key: "clinic",
    label: "Clinic visit",
    icon: Stethoscope,
    template: "05-healthcare-triage-booking",
    action: "Call the clinic",
    brief: "You've had a sore throat and a fever for three days. Call the clinic's front desk and get seen tomorrow.",
    lines: ["I've had a fever since Sunday and my throat really hurts.", "Can I come in tomorrow morning?"],
  },
  {
    key: "roadside",
    label: "Roadside help",
    icon: BatteryLow,
    template: "06-automotive-roadside-ev",
    action: "Call roadside help",
    brief: "Your electric car is down to 2% on the highway. You're parked safely on the shoulder and need a charge or a tow.",
    lines: ["My car's battery is almost flat and I've pulled over.", "Yes, I'm safe, I'm on the hard shoulder."],
  },
  {
    key: "loan",
    label: "Payment reminder",
    icon: Landmark,
    template: "01-banking-collections",
    action: "Take the bank's call",
    brief: "Acme Bank calls you, Jordan, about a missed $240 loan payment. You can pay it in full on Friday.",
    lines: ["Yes, this is Jordan.", "I can pay the whole amount on Friday."],
  },
];
