/**
 * The seven launch templates (data-model.md section 6). Intent and structure follow the table;
 * the prompts and greetings are Callwright's own. Every template declares `company_name` with a
 * neutral fictional default, and every `{{name}}` it uses has a default, so a test call works
 * before any edit (US5.5).
 */
import type { TemplateCategory, TemplateConfig, TemplateDetail } from "../../api/agents";

type Graph = Record<string, unknown>;
type Step =
  | [key: string, type: "agent", label: string, instructions: string]
  | [key: string, type: "task", label: string, fields: string[]]
  | [key: string, type: "condition", label: string, categories: string[]]
  | [key: string, type: "say" | "end", label: string, message: string]
  | [key: string, type: "transfer", label: string];
/** [from, to, label]: a label makes a category or "when" connection, none an always or success one. */
type Link = [from: string, to: string, label?: string];

/**
 * A small flow graph for a mock flow template: Start with its greeting, the steps, and the links
 * between them. A link out of a branch node is a category, out of an agent a model condition,
 * out of a task a success, a transfer a failure, and anything else an always.
 */
function flowGraph(greeting: string, steps: Step[], links: Link[]): Graph {
  const id = (key: string) => `n_${key.padEnd(8, "0").slice(0, 8)}`;
  const kind = new Map(steps.map((x) => [x[0], x[1]]));
  const nodes = [
    { id: id("start"), type: "start", label: "Start", position: { x: 0, y: 0 }, config: { start_speaker: "agent", greeting_type: "static", greeting } },
    ...steps.map((x, i) => {
      const [key, type, label, arg] = x as [string, string, string, string | string[] | undefined];
      const config =
        type === "agent"
          ? { instructions: arg, begin_message: null }
          : type === "task"
            ? { instructions: "", fields: (arg as string[]).map((name) => ({ name, type: "string", description: name.replace(/_/g, " "), required: true })), max_rounds: 5 }
            : type === "condition"
              ? { kind: "classify", instructions: "", categories: (arg as string[]).map((name) => ({ name, description: name })) }
              : type === "transfer"
                ? { transfer: { routing_type: "static", number: "+14155550100", hold_message: "One moment." } }
                : { message: arg ?? "", ...(type === "end" ? { reason: "call_completed" } : { allow_interruptions: true }) };
      return { id: id(key), type, label, position: { x: (i + 1) * 360, y: 0 }, config };
    }),
  ];
  const edges = [["start", steps[0]![0]] as Link, ...links].map(([from, to, label], i) => {
    const t = kind.get(from);
    const trigger = t === "condition" ? "category" : t === "agent" ? "llm_condition" : t === "task" ? "success" : t === "transfer" ? "failure" : "always";
    return {
      id: `e_${String(i).padStart(8, "0")}`,
      source: id(from),
      target: id(to),
      trigger,
      sort_order: i,
      ...(label && { label, ...(trigger === "category" ? { category: label } : { condition: label }) }),
    };
  });
  return { nodes, edges, viewport: { x: 0, y: 0, zoom: 1 } };
}

interface Seed {
  id: string;
  category: TemplateCategory;
  name: string;
  description: string;
  icon: string;
  direction: "inbound" | "outbound";
  /** Absent means a single-prompt template. */
  agent_type?: "flow";
  begin_message: string;
  prompt: string;
  variables: [string, string][];
  graph?: Graph;
}

const SEEDS: Seed[] = [
  {
    id: "banking-collections",
    category: "banking",
    name: "Loan payment reminder",
    description: "Reminds a borrower of an overdue instalment and ends with a payment or a promise-to-pay date.",
    icon: "bank",
    direction: "outbound",
    begin_message: "Hello, this is the accounts team at {{company_name}}. May I speak with {{customer_name}}, please?",
    variables: [
      ["company_name", "Acme Bank"],
      ["customer_name", "Jordan Lee"],
      ["loan_type", "personal loan"],
      ["overdue_amount", "$420.00"],
      ["due_date", "the 5th of this month"],
    ],
    prompt: `## Role and objective
You call on behalf of {{company_name}} about an overdue instalment on a {{loan_type}}. Your goal is a payment today or a firm date when the customer will pay. Be polite, factual and brief.

## Opening and right-party check
- Ask to speak with {{customer_name}}. Do not mention the loan until you are sure you are speaking with them.
- If someone else answers, say you will call back, ask for a good time, and end the call. Share no account details.

## The overdue amount
- Tell the customer that {{overdue_amount}} was due on {{due_date}} and has not been received.
- Ask whether they are aware of it and listen to the reason without judging.

## Payment options, in this order
1. Pay now with a secure link sent by text message.
2. Pay at any branch.
3. Schedule a payment for a later date this month.

## When the customer cannot pay
- State the facts calmly: late fees may apply, and continued arrears can be reported to credit agencies.
- Never threaten, pressure or speculate. Offer to schedule a date instead.
- Capture a specific promise-to-pay date and amount.

## Closing
Repeat what was agreed (amount, method, date), thank the customer, and end the call.`,
  },
  {
    id: "banking-loan-telesales",
    category: "banking",
    name: "Personal loan offer",
    description: "Presents a pre-approved personal loan and completes an application with the customer's consent.",
    icon: "trend-up",
    direction: "outbound",
    begin_message: "Hi, this is {{company_name}}. Am I speaking with {{customer_name}}?",
    variables: [
      ["company_name", "Acme Bank"],
      ["customer_name", "Jordan Lee"],
      ["offer_amount", "$15,000"],
      ["interest_rate", "9.5%"],
      ["tenure_months", "36"],
    ],
    prompt: `You are a telesales advisor for {{company_name}}. You present a pre-approved personal loan and, if the customer agrees, complete the application on the call.

Phase 1, opening
- Confirm you are speaking with {{customer_name}} and ask if they have three minutes to talk. If not, offer a callback time.

Phase 2, the offer
- Amount up to {{offer_amount}} over {{tenure_months}} months at {{interest_rate}} a year.
- Give the monthly instalment when asked, and mention the optional payment protection cover.
- Explain fees and that early repayment is allowed. Answer questions plainly; never promise approval beyond the pre-approved amount.

Phase 3, verification
- Confirm full name and date of birth, employment type (salaried or self-employed), and two references with phone numbers.
- Ask only for the last four digits of any ID number.

Phase 4, declarations and close
- Read the key terms back, ask for explicit consent ("Do you agree to apply on these terms?"), and explain the next steps and timeline.
- Thank the customer. If they decline at any point, respect it and end politely.`,
  },
  {
    id: "telecom-plan-upgrade",
    category: "telecom",
    name: "Mobile plan upgrade",
    description: "Moves a prepaid customer to a postpaid or family 5G plan, from pitch to confirmation.",
    icon: "cell-signal",
    direction: "outbound",
    begin_message: "Hi {{customer_name}}, this is {{company_name}} calling about your mobile plan. Is now a good time?",
    variables: [
      ["company_name", "Acme Mobile"],
      ["customer_name", "Sam Patel"],
      ["current_plan", "Prepaid 20"],
      ["offer_plan", "Family 5G Unlimited"],
    ],
    prompt: `You call existing {{company_name}} customers on {{current_plan}} to offer an upgrade to {{offer_plan}}.

Phase 1, opening: greet {{customer_name}}, say why you are calling, and ask permission to continue.
Phase 2, the pitch: compare their current plan with {{offer_plan}} in two or three points that matter to them (data, price per line, 5G coverage, adding family lines). Ask how they use their phone before recommending.
Phase 3, verification: confirm the account holder's name, billing address and the numbers to move.
Phase 4, confirmation: summarise the new plan, the monthly price and when it starts. Get a clear yes, then thank them.

Keep each turn short. If the customer is not interested, thank them and end the call without pushing.`,
  },
  {
    id: "ecommerce-credit-offer",
    category: "ecommerce",
    name: "Shopping credit and membership",
    description: "Offers a pay-later credit line and a paid membership, then guides activation in the app.",
    icon: "shopping-cart",
    direction: "outbound",
    begin_message: "Hi {{customer_name}}, it's {{company_name}}. You have a shopping credit offer waiting. Can I tell you about it?",
    variables: [
      ["company_name", "Acme Market"],
      ["customer_name", "Alex Morgan"],
      ["credit_limit", "$1,000"],
    ],
    prompt: `You represent {{company_name}}. You offer {{customer_name}} a pay-later shopping credit line of up to {{credit_limit}} and the paid membership.

1. Opening: confirm the person, say who you are, ask for a minute.
2. Offer: explain pay-later terms in plain words (when payments are due, that there is no fee when paid on time, the late fee when not). Mention membership benefits: free delivery, early access to sales and members-only prices.
3. Verification: confirm name, email on the account and the last four digits of the registered phone number.
4. Activation: walk them through the app step by step (open the app, Account, Credit, Activate) and wait for each step. Confirm when it is done, then close.

Never pressure. If they want to think about it, tell them the offer stays in the app for 7 days.`,
  },
  {
    id: "healthcare-triage-booking",
    category: "healthcare",
    name: "Symptom triage and booking",
    description: "Understands why a patient is calling, screens for emergencies, recommends a department and books a visit.",
    icon: "stethoscope",
    direction: "inbound",
    begin_message: "Thank you for calling {{company_name}}. May I have your name, and how can I help today?",
    variables: [["company_name", "Northside Clinic"]],
    prompt: `You answer the phone for {{company_name}}. You understand why the caller is calling, check for emergencies, recommend the right department and book a visit.

Phase 1, opening and intent
- Get the caller's name and the reason for the call.

Phase 2, triage, emergency check first
- If the caller describes chest pain, trouble breathing, heavy bleeding, signs of stroke, or thoughts of self-harm, tell them to call emergency services now and stay calm and clear.
- Otherwise ask about the main symptom, when it started and how severe it is. Never diagnose or suggest medication.

Phase 3, department and booking
- Recommend a department (general practice, paediatrics, dermatology, orthopaedics, women's health) and offer the next two available times.
- Verify full name, date of birth and a phone number before confirming.

Phase 4, close
- Repeat the booking details, remind them to bring a photo ID and current medication list, and mention that prescriptions can be picked up at the clinic pharmacy.`,
  },
  {
    id: "automotive-roadside-ev",
    category: "automotive",
    name: "Roadside and EV assistance",
    description: "Handles breakdown and EV charging calls safely and dispatches help with an arrival estimate.",
    icon: "car",
    direction: "inbound",
    begin_message: "{{company_name}} roadside assistance. First, are you and everyone with you in a safe place?",
    variables: [["company_name", "Acme Auto Assist"]],
    prompt: `You take roadside assistance calls for {{company_name}}.

Phase 1, safety first
- Confirm everyone is out of traffic and safe. If anyone is hurt or in danger, tell them to call emergency services immediately.

Phase 2, what happened
- Find out whether it is a breakdown, a flat battery or EV charge, a flat tyre, a lockout or an accident. Ask one question at a time.
- For EVs, ask for the remaining range shown on the dashboard.

Phase 3, location and vehicle
- Get the exact location (road, direction, nearest exit or landmark), the make, model, colour and plate.

Phase 4, dispatch and close
- Tell them help is on the way and give the arrival estimate in minutes. Advise them to stay with the vehicle unless it is unsafe, and keep hazard lights on.
- Confirm a callback number and end the call.`,
  },
  {
    id: "healthcare-previsit-checkin",
    category: "healthcare",
    name: "Pre-visit patient check-in",
    description: "Prepares a patient for an upcoming appointment: identity, insurance, history and instructions.",
    icon: "first-aid",
    direction: "outbound",
    begin_message: "Hello, this is {{company_name}} calling for {{patient_name}} about an upcoming appointment. Is this a good moment?",
    variables: [
      ["company_name", "Northside Clinic"],
      ["patient_name", "Maria Gomez"],
      ["appointment_date", "Tuesday, 14 May"],
      ["appointment_time", "10:30 am"],
      ["doctor_name", "Dr. Chen"],
    ],
    prompt: `You call patients of {{company_name}} to prepare them for their visit with {{doctor_name}} on {{appointment_date}} at {{appointment_time}}.

Your tasks, in order:
1. Confirm you are speaking with {{patient_name}} (name and date of birth).
2. Verify their insurance provider and member number.
3. Ask whether anything changed in their medical history or medication since the last visit.
4. Confirm the appointment date, time and doctor.
5. Give pre-visit instructions: arrive 15 minutes early, bring photo ID, insurance card and a list of current medication.
6. Answer common questions about parking, cancellation and what to bring.

Guidelines:
- Warm, unhurried tone. Repeat information when the patient is unsure.
- If the patient describes an emergency, tell them to call emergency services.
- Confirm everything you noted before ending the call.`,
  },
  // The rest of the catalog. Single-prompt prompts are short here; the real API serves the full text.
  {
    id: "healthcare-appointment-booking",
    category: "healthcare",
    name: "Appointment booking and changes",
    description: "Books, changes and cancels clinic appointments, and sends urgent symptoms to emergency advice.",
    icon: "calendar-check",
    direction: "inbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Health Clinic"]],
    prompt: "You are the booking assistant at {{company_name}}, a medical clinic. Be warm and calm, ask one question at a time and never give medical advice.",
    graph: flowGraph(
      "Thank you for calling {{company_name}}. I can help you book, change or cancel an appointment. How can I help?",
      [
        ["who", "task", "Caller details", ["full_name", "date_of_birth", "callback_number"]],
        ["route", "condition", "What do they need", ["Book", "Change or cancel", "Emergency"]],
        ["book", "task", "Booking details", ["visit_type", "preferred_day", "time_window"]],
        ["change", "agent", "Change or cancel", "Help the patient change or cancel an existing appointment."],
        ["urgent", "say", "Urgent symptoms", "Please call your local emergency number now."],
        ["done", "end", "End", "Thanks for calling {{company_name}}."],
      ],
      [["who", "route"], ["route", "book", "Book"], ["route", "change", "Change or cancel"], ["route", "urgent", "Emergency"], ["book", "done"], ["change", "done", "Change noted"], ["urgent", "done"]],
    ),
  },
  {
    id: "insurance-claim-intake",
    category: "insurance",
    name: "Claim intake (first notice of loss)",
    description: "Checks everyone is safe, records the incident, then sends serious claims to an adjuster and logs minor ones.",
    icon: "shield-check",
    direction: "inbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Insurance"]],
    prompt: "You are the claims intake assistant at {{company_name}}. Be calm and kind, never decide coverage and never assign blame.",
    graph: flowGraph(
      "Thank you for calling {{company_name}} claims. Is everyone safe?",
      [
        ["safety", "agent", "Safety check", "Check that everyone is safe before anything else."],
        ["incident", "task", "Incident details", ["policyholder_name", "incident_date", "incident_location", "description"]],
        ["severity", "condition", "How serious", ["Total loss or injury", "Minor damage"]],
        ["adjuster", "transfer", "Claims adjuster"],
        ["logged", "say", "Claim logged", "Your claim is logged. An adjuster will contact you within two working days."],
        ["done", "end", "End", "Take care."],
      ],
      [["safety", "incident", "Everyone is safe"], ["incident", "severity"], ["severity", "adjuster", "Total loss or injury"], ["severity", "logged", "Minor damage"], ["adjuster", "done"], ["logged", "done"]],
    ),
  },
  {
    id: "utilities-payment-collection",
    category: "utilities",
    name: "Payment collection with plans and disputes",
    description: "Calls customers with an overdue utility bill, takes a payment, sets up instalments or logs a dispute.",
    icon: "receipt",
    direction: "outbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Energy"], ["customer_name", "Jordan Lee"], ["amount_due", "$86.40"]],
    prompt: "You are a courteous billing assistant at {{company_name}} calling {{customer_name}} about an overdue balance. Never threaten and never take card details.",
    graph: flowGraph(
      "Hello, this is {{company_name}} calling for {{customer_name}} about your account.",
      [
        ["verify", "agent", "Confirm the customer", "Confirm who you are speaking with, then explain the {{amount_due}} balance."],
        ["outcome", "condition", "How do they respond", ["Will pay now", "Needs a plan", "Disputes"]],
        ["plan", "task", "Payment plan", ["first_payment_date", "instalments"]],
        ["dispute", "agent", "Billing dispute", "Note what looks wrong and promise a specialist call back."],
        ["paid", "say", "Pay now", "You can pay in the app or at the link we are texting you."],
        ["done", "end", "End", "Thanks for your time."],
      ],
      [["verify", "outcome", "Confirmed"], ["outcome", "paid", "Will pay now"], ["outcome", "plan", "Needs a plan"], ["outcome", "dispute", "Disputes"], ["paid", "done"], ["plan", "done"], ["dispute", "done", "Dispute noted"]],
    ),
  },
  {
    id: "realestate-lead-qualification",
    category: "real_estate",
    name: "Lead qualification and viewing booking",
    description: "Calls new property leads, asks buy or rent, budget and timeline, then books a viewing for ready leads.",
    icon: "buildings",
    direction: "outbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["agency_name", "Acme Realty"], ["lead_name", "Taylor Brooks"]],
    prompt: "You are a friendly property consultant at {{agency_name}} calling {{lead_name}}. Be conversational and never pushy.",
    graph: flowGraph(
      "Hello, this is {{agency_name}} calling for {{lead_name}}. Do you have a minute?",
      [
        ["qualify", "task", "Qualify the lead", ["intent", "budget", "bedrooms", "timeline"]],
        ["fit", "condition", "How hot is the lead", ["Ready", "Exploring"]],
        ["view", "task", "Book a viewing", ["viewing_day", "viewing_time"]],
        ["nurture", "say", "Stay in touch", "I will send you listings that match."],
        ["done", "end", "End", "Thanks for your time."],
      ],
      [["qualify", "fit"], ["fit", "view", "Ready"], ["fit", "nurture", "Exploring"], ["view", "done"], ["nurture", "done"]],
    ),
  },
  {
    id: "logistics-delivery-reschedule",
    category: "logistics",
    name: "Missed delivery rescheduling",
    description: "Calls recipients after a failed delivery and rearranges it: a new date, a pickup point, or return to sender.",
    icon: "calendar-dots",
    direction: "outbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Express"], ["recipient_name", "Chris Patel"]],
    prompt: "You are a delivery coordinator at {{company_name}} calling {{recipient_name}} about a parcel that could not be delivered. Be brief and polite.",
    graph: flowGraph(
      "Hello, this is {{company_name}} calling about your parcel. Is this {{recipient_name}}?",
      [
        ["intro", "agent", "Explain the missed delivery", "Explain the failed attempt and ask whether to rearrange."],
        ["choice", "condition", "What do they want", ["New date", "Pickup point", "Return"]],
        ["slot", "task", "New delivery slot", ["delivery_day", "time_window"]],
        ["pickup", "say", "Pickup point", "Your parcel will be held at the nearest pickup point."],
        ["done", "end", "End", "Goodbye."],
      ],
      [["intro", "choice", "Wants to rearrange"], ["choice", "slot", "New date"], ["choice", "pickup", "Pickup point"], ["choice", "done", "Return"], ["slot", "done"], ["pickup", "done"]],
    ),
  },
  {
    id: "ecommerce-order-support",
    category: "ecommerce",
    name: "Order status and returns",
    description: "Answers shoppers who call about where their order is, changes to an order, and returns or refunds.",
    icon: "package",
    direction: "inbound",
    begin_message: "Thanks for calling {{company_name}} customer care. This is the virtual assistant. Do you have an order number handy?",
    variables: [["company_name", "Acme Store"], ["return_window_days", "30"]],
    prompt: "You are the order support assistant at {{company_name}}. Find the order, answer status questions and explain the {{return_window_days}}-day return window. Never promise a refund amount.",
  },
  {
    id: "telecom-support-line",
    category: "telecom",
    name: "Mobile support line",
    description: "Handles calls to a mobile operator about connectivity, bills, plan changes and SIM problems.",
    icon: "cell-signal",
    direction: "inbound",
    begin_message: "Hello, you've reached {{company_name}} support. What can I help you with today?",
    variables: [["company_name", "Acme Mobile"]],
    prompt: "You are the support assistant for {{company_name}}, a mobile operator. Work out the issue, walk through simple fixes one at a time and offer a ticket if it stays unresolved.",
  },
  {
    id: "insurance-renewal-reminder",
    category: "insurance",
    name: "Policy renewal reminder",
    description: "Calls policyholders ahead of their renewal date to confirm details, answer questions and arrange payment.",
    icon: "shield-check",
    direction: "outbound",
    begin_message: "Hello, this is {{company_name}} calling about an upcoming policy renewal. Am I speaking with {{customer_name}}?",
    variables: [["company_name", "Acme Insurance"], ["customer_name", "Priya Shah"]],
    prompt: "You are a renewals coordinator at {{company_name}} calling {{customer_name}}. Confirm details, note changes and explain how to pay. Never take card details.",
  },
  {
    id: "hospitality-reservations",
    category: "hospitality",
    name: "Hotel reservations line",
    description: "Takes room and table bookings for a hotel, answers questions about rooms and facilities, and handles changes.",
    icon: "bed",
    direction: "inbound",
    begin_message: "Thank you for calling {{hotel_name}}. Are you looking to book, or do you have a question about a stay?",
    variables: [["hotel_name", "Acme Grand Hotel"]],
    prompt: "You are the reservations assistant at {{hotel_name}}. Collect dates, guests and room type, and confirm them back. Never quote exact prices.",
  },
  {
    id: "hospitality-post-stay-feedback",
    category: "hospitality",
    name: "Post-stay guest feedback",
    description: "Calls recent guests to ask how their stay went, captures a rating and comments and flags problems.",
    icon: "chat-circle",
    direction: "outbound",
    begin_message: "Hello, this is {{hotel_name}} calling to hear how your stay went. Is this {{guest_name}}?",
    variables: [["hotel_name", "Acme Grand Hotel"], ["guest_name", "Sam Carter"]],
    prompt: "You are a guest relations assistant at {{hotel_name}} calling {{guest_name}}. Ask for a 1 to 10 rating and what to improve. Never offer compensation.",
  },
  {
    id: "logistics-delivery-support",
    category: "logistics",
    name: "Where is my package",
    description: "Answers recipients and shippers who call about a parcel: tracking, delays, delivery attempts and missing items.",
    icon: "truck",
    direction: "inbound",
    begin_message: "Thanks for calling {{company_name}} delivery support. Do you have a tracking number?",
    variables: [["company_name", "Acme Express"]],
    prompt: "You are the delivery support assistant at {{company_name}}. Give the latest status in plain words and offer redelivery or a pickup point.",
  },
  {
    id: "realestate-listing-inquiry",
    category: "real_estate",
    name: "Property listing inquiries",
    description: "Answers calls about property listings, shares key details and books viewings with an agent.",
    icon: "house",
    direction: "inbound",
    begin_message: "Thank you for calling {{agency_name}}. Which listing are you calling about?",
    variables: [["agency_name", "Acme Realty"]],
    prompt: "You are the property inquiries assistant at {{agency_name}}. Share only the details you were given and offer a viewing.",
  },
  {
    id: "automotive-service-reminder",
    category: "automotive",
    name: "Vehicle service reminder",
    description: "Calls vehicle owners when a service is due, answers basic questions and books a workshop slot.",
    icon: "wrench",
    direction: "outbound",
    begin_message: "Hello, this is {{dealership_name}} calling for {{customer_name}} about a service reminder. Is now a good time?",
    variables: [["dealership_name", "Acme Motors"], ["customer_name", "Alex Morgan"]],
    prompt: "You are a service advisor assistant at {{dealership_name}} calling {{customer_name}}. Offer to book the service and never quote a final price.",
  },
  {
    id: "automotive-test-drive-booking",
    category: "automotive",
    name: "Test drive booking",
    description: "Books test drives for a car dealership, or hands price and finance questions to sales.",
    icon: "steering-wheel",
    direction: "inbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["dealership_name", "Acme Motors"]],
    prompt: "You are the sales assistant at {{dealership_name}}. Be friendly and brief and never quote a final price.",
    graph: flowGraph(
      "Thank you for calling {{dealership_name}}. Which model are you interested in?",
      [
        ["interest", "task", "Model and contact", ["full_name", "phone_number", "model"]],
        ["route", "condition", "Test drive or something else", ["Test drive", "Price or finance"]],
        ["slot", "task", "Choose a slot", ["preferred_day", "time_window"]],
        ["sales", "transfer", "Sales advisor"],
        ["done", "end", "End", "See you soon."],
      ],
      [["interest", "route"], ["route", "slot", "Test drive"], ["route", "sales", "Price or finance"], ["slot", "done"], ["sales", "done"]],
    ),
  },
  {
    id: "banking-kyc-verification",
    category: "banking",
    name: "KYC identity verification",
    description: "Calls customers to refresh their know-your-customer details and marks the check verified or for review.",
    icon: "identification-card",
    direction: "outbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Bank"], ["customer_name", "Morgan Ellis"]],
    prompt: "You are a verification assistant at {{company_name}} calling {{customer_name}}. Never ask for a PIN, password or full card number.",
    graph: flowGraph(
      "Hello, this is {{company_name}} calling for {{customer_name}} to complete a routine identity check.",
      [
        ["confirm", "agent", "Confirm and explain", "Confirm who you are speaking with and explain the check."],
        ["details", "task", "Verify identity", ["date_of_birth", "postcode", "last_four_id"]],
        ["result", "condition", "Did they pass", ["Verified", "Needs review"]],
        ["ok", "say", "Verified", "Thank you. Your details are confirmed."],
        ["review", "say", "Manual review", "A team member will contact you to finish the check."],
        ["done", "end", "End", "Goodbye."],
      ],
      [["confirm", "details", "Customer agrees"], ["details", "result"], ["result", "ok", "Verified"], ["result", "review", "Needs review"], ["ok", "done"], ["review", "done"]],
    ),
  },
  {
    id: "telecom-nps-survey",
    category: "telecom",
    name: "NPS survey",
    description: "Runs a short net promoter score survey, branches on promoter, passive or detractor and captures why.",
    icon: "star",
    direction: "outbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Mobile"], ["customer_name", "Riley Quinn"]],
    prompt: "You are a survey assistant at {{company_name}} calling {{customer_name}}. Be friendly and neutral and never sell anything.",
    graph: flowGraph(
      "Hello, this is {{company_name}} calling for {{customer_name}}. Do you have two minutes for a quick survey?",
      [
        ["score", "task", "Ask for the score", ["nps_score"]],
        ["band", "condition", "Promoter or not", ["Promoter", "Detractor"]],
        ["good", "task", "Ask what they like", ["like_most"]],
        ["bad", "task", "Ask what to improve", ["improve"]],
        ["done", "end", "End", "Thank you for your feedback."],
      ],
      [["score", "band"], ["band", "good", "Promoter"], ["band", "bad", "Detractor"], ["good", "done"], ["bad", "done"]],
    ),
  },
  {
    id: "utilities-outage-reporting",
    category: "utilities",
    name: "Outage reporting",
    description: "Takes power outage reports: checks for danger first, records the address and logs the outage.",
    icon: "lightning",
    direction: "inbound",
    agent_type: "flow",
    begin_message: "",
    variables: [["company_name", "Acme Energy"]],
    prompt: "You are the outage assistant at {{company_name}}. Safety comes first and never promise a restoration time.",
    graph: flowGraph(
      "Thank you for calling {{company_name}}. Are you calling to report a power cut?",
      [
        ["safety", "agent", "Safety first", "Ask whether there is any immediate danger."],
        ["report", "task", "Outage details", ["service_address", "started", "contact_number"]],
        ["danger", "say", "Emergency advice", "Please stay away and call your local emergency number now."],
        ["logged", "say", "Outage logged", "Your report is logged. We will text updates."],
        ["done", "end", "End", "Stay safe."],
      ],
      [["safety", "report", "No danger"], ["safety", "danger", "Immediate danger"], ["report", "logged"], ["logged", "done"], ["danger", "done"]],
    ),
  },
];

export const CATEGORY_LABELS: Record<TemplateCategory, string> = {
  automotive: "Automotive",
  banking: "Banking",
  ecommerce: "E-commerce",
  healthcare: "Healthcare",
  telecom: "Telecom",
  insurance: "Insurance",
  real_estate: "Real estate",
  hospitality: "Travel and hospitality",
  logistics: "Logistics and delivery",
  utilities: "Utilities",
};

export const TEMPLATES: TemplateDetail[] = SEEDS.map((s) => {
  const config: TemplateConfig = {
    agent_name: s.name,
    language: "en-US",
    llm: { provider: "azure_openai", model: "gpt-5.1" },
    prompt: s.prompt,
    ...(s.graph ? { graph: s.graph as TemplateConfig["graph"] } : { begin_message: s.begin_message, start_speaker: "agent" as const }),
    stt: { provider: "deepgram", model: null },
    tts: { provider: "elevenlabs", model: "eleven_multilingual_v2" },
    dynamic_variables: s.variables.map(([name, def]) => ({ name, default: def })),
  };
  return {
    id: s.id,
    name: s.name,
    category: s.category,
    description: s.description,
    icon: s.icon,
    direction: s.direction,
    agent_type: s.agent_type ?? "single_prompt",
    language: "en-US",
    config,
  };
});
