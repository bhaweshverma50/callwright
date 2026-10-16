# Channels: SIP numbers and WhatsApp (`/phone-numbers`)

Live walkthrough, 2026-10-16. The account has no numbers or channels, so the number detail panel (inbound/outbound agent attach, inbound webhook, "Make outbound call" dialog, caller routes) could not be reached. Screens: `screens/phone-*`.

## Page

- Sidebar label "Phone Numbers", but the page eyebrow is "CHANNELS": title "Every number, one roof.", subtitle "Import numbers, attach agents, and manage call routing across SIP and WhatsApp."
- Tabs: **SIP numbers** (default), **WhatsApp channels**. The primary button follows the tab: "Import number" / "Add WhatsApp channel".
- GETs: `/phone-numbers/`, `/whatsapp/channels`.
- Empty states: SIP "No phone numbers yet / Click "Import Number" to add your first phone number". WhatsApp "No WhatsApp Channels / Add a WhatsApp channel to receive inbound voice calls via WhatsApp."

## Import Phone Number dialog (SIP, bring your own trunk)

Top info block: **CallDash Origination URI**: "You will have to put this as origination URI in your telephony provider for inbound calls", value `sip:1bf5vp09rrg.sip.livekit.cloud` with a copy button. (One fixed LiveKit Cloud SIP URI for the whole platform, not per account.)

| Field | Control | Placeholder | Helper | Validation (on submit) |
|---|---|---|---|---|
| Phone Number \* | text | +14155551234 | "E.164 format (e.g., +14155551234)" | "Phone number must be in E.164 format (e.g., +14155551234)" |
| Label \* | text | Main Office Line | | required |
| SIP Trunk Termination URI \* | text | termination.example.com or 192.168.1.1:5060 | "Enter hostname or IP address (with optional port)" and a second line "You will get this from your telephone provider" | `sip:term.example.com` gives "Enter hostname or IP address only (e.g., termination.example.com or 192.168.1.1), not a full SIP URI" |
| Username (Optional) | text | SIP trunk username | | |
| Password (Optional) | password | SIP trunk password | | |
| Cancel / Import Number | buttons | | | Submitting an empty form shows no inline messages (fields stay in their default state). |

Blocked: POST `/phone-numbers/import` `{phone_number, user_id, label, sip_trunk_termination_uri, username, password}`. Failure: "Network Error" snackbar, dialog stays open.

No carrier picker, no number search/purchase, no region or capability fields, no transport (UDP/TCP/TLS) or media-encryption options.

## Add WhatsApp Channel dialog

| Field | Control | Default / placeholder | Helper | Validation |
|---|---|---|---|---|
| Label \* | text | "My WhatsApp Business" | | native required |
| Phone Number \* | text | "+919310928479" | "The actual phone number in E.164 format" | "Phone number must be in E.164 format (e.g., +919310928479)" |
| WhatsApp Phone Number ID \* | text | "e.g., 123456789012345" | "From Meta Business app settings" | none ("abc" accepted) |
| WhatsApp Business API Token \* | password | "Your API token" | | native required |
| Cloud API Version | text | 23.0 | "Meta Cloud API version (default: 23.0)" | |
| CallDash Webhook URL | read-only block + copy | `https://calldash-api-prod.azurewebsites.net/api/whatsapp/webhook` | "Set this as the Callback URL in your Meta WhatsApp app webhook settings" | |
| Meta Verify Token \* | text | "Your webhook verify token" | "Used for Meta webhook verification" | native required |
| (icon) Open Meta Business documentation | icon button | | | |
| Cancel / Add Channel | buttons | | | |

- Required fields use native browser validation ("Please fill in this field.").
- Blocked: POST `/whatsapp/channels` `{whatsapp_phone_number_id, phone_number, label, whatsapp_api_token, whatsapp_cloud_api_version, meta_verify_token}`. Failure snackbar: "Failed to create WhatsApp channel. Please try again."
- The webhook URL is one shared platform endpoint; the user supplies their own verify token.

## Not reachable (needs an imported number or channel)

Number detail panel (inbound agent, inbound webhook URL, outbound agent, Save/Cancel/Delete), "Make outbound call" dialog with dynamic variables, WhatsApp attach-agent and caller routes. See functional spec section 9 for the bundle-derived contract.
