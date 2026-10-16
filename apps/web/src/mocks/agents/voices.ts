/**
 * Voice lists per provider for the mock voice browser (contracts/voices.yaml Voice). ElevenLabs
 * and Cartesia stand in for live vendor listings; Fish Audio is the platform's curated allow-list
 * of business-suitable voices (FR-045), never the vendor's community library.
 */
import type { Voice } from "../../api/agents";
import { chimeDataUri } from "./audio";

type Row = [id: string, name: string, description: string, gender: Voice["gender"], languages: string[]];

const EN = ["en", "en-US", "en-GB", "en-AU", "en-NZ", "en-IN"];

const ELEVEN: Row[] = [
  ["el_jessica", "Jessica", "Bright and warm. A friendly front-desk voice that keeps callers at ease.", "female", EN],
  ["el_sarah", "Sarah", "Mature and reassuring, with a calm pace for support and billing calls.", "female", EN],
  ["el_matilda", "Matilda", "Knowledgeable and professional; good for explaining policies.", "female", ["en", "en-US"]],
  ["el_laura", "Laura", "Upbeat and quick; suits sales and appointment reminders.", "female", ["en", "en-US"]],
  ["el_alice", "Alice", "Clear British educator; precise and easy to follow.", "female", ["en", "en-GB"]],
  ["el_lily", "Lily", "Soft, velvety British voice for hospitality and healthcare.", "female", ["en", "en-GB"]],
  ["el_liam", "Liam", "Articulate and young, with a confident, steady tone.", "male", ["en", "en-US"]],
  ["el_brian", "Brian", "Deep and steady. Sounds dependable on long explanations.", "male", ["en", "en-US"]],
  ["el_charlie", "Charlie", "Easy-going Australian voice with natural energy.", "male", ["en", "en-AU"]],
  ["el_george", "George", "Warm British storyteller; patient on complex calls.", "male", ["en", "en-GB"]],
  ["el_daniel", "Daniel", "Authoritative British newsreader; crisp and formal.", "male", ["en", "en-GB"]],
  ["el_will", "Will", "Friendly and optimistic; good for outbound offers.", "male", ["en", "en-US"]],
  ["el_eric", "Eric", "Smooth and trustworthy; a safe choice for collections.", "male", ["en", "en-US"]],
  ["el_river", "River", "Relaxed and neutral, neither high nor low.", "neutral", ["en", "en-US"]],
  [
    "el_anika",
    "Anika",
    "Natural Hindi and Indian English customer care voice.",
    "female",
    ["hi", "hi-Latn", "en-IN", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"],
  ],
  ["el_aarav", "Aarav", "Calm Hindi and Indian English support voice.", "male", ["hi", "hi-Latn", "en-IN"]],
  ["el_sofia", "Sofia", "Warm Spanish support voice, neutral accent.", "female", ["es", "es-419"]],
  ["el_amelie", "Amelie", "Polished French voice for European and Canadian callers.", "female", ["fr", "fr-CA"]],
  ["el_jonas", "Jonas", "Calm, precise German voice.", "male", ["de"]],
  ["el_yuki", "Yuki", "Gentle Japanese voice for service lines.", "female", ["ja"]],
];

const CARTESIA: Row[] = [
  ["ca_skylar", "Skylar", "Friendly guide with a light, helpful tone.", "female", EN],
  ["ca_daniel", "Daniel", "Modern assistant; efficient and polite.", "male", EN],
  ["ca_gemma", "Gemma", "Decisive agent who keeps calls moving.", "female", ["en", "en-GB"]],
  ["ca_parker", "Parker", "Supportive and patient on troubleshooting calls.", "male", ["en", "en-US"]],
  ["ca_archie", "Archie", "Approachable British mate.", "male", ["en", "en-GB"]],
  ["ca_jacqueline", "Jacqueline", "Reassuring agent for sensitive conversations.", "female", ["en", "en-US"]],
  ["ca_clive", "Clive", "Measured expert; slow and deliberate.", "male", ["en", "en-GB"]],
  ["ca_ella", "Ella", "Caring and bright; good for healthcare check-ins.", "female", ["en", "en-US"]],
  ["ca_arlo", "Arlo", "Service specialist with a steady rhythm.", "male", ["en", "en-AU"]],
  ["ca_cora", "Cora", "Service specialist; warm and concise.", "female", ["en", "en-US"]],
  ["ca_zander", "Zander", "Composed advisor for financial calls.", "male", ["en", "en-US"]],
  ["ca_lauren", "Lauren", "Lively narrator; energetic delivery.", "female", ["en", "en-US"]],
  ["ca_morgan", "Morgan", "Even, gender-neutral voice.", "neutral", ["en", "en-US"]],
  ["ca_ishan", "Ishan", "Clear Hindi and Indian English voice.", "male", ["hi", "en-IN"]],
  ["ca_priya", "Priya", "Friendly Hindi support voice.", "female", ["hi", "en-IN"]],
  [
    "ca_lucia",
    "Lucia",
    "Multilingual voice for Spanish, French, Italian and Portuguese.",
    "female",
    ["es", "es-419", "fr", "fr-CA", "it", "pt", "pt-BR", "multi"],
  ],
  ["ca_mateo", "Mateo", "Spanish support voice with a Latin American accent.", "male", ["es", "es-419"]],
  ["ca_hanna", "Hanna", "Calm German and Dutch voice.", "female", ["de", "nl"]],
  ["ca_kenji", "Kenji", "Polite Japanese voice.", "male", ["ja"]],
  ["ca_minji", "Min-ji", "Bright Korean voice.", "female", ["ko"]],
];

const FISH: Row[] = [
  ["fa_aria", "Aria", "Professional English receptionist voice.", "female", EN],
  ["fa_owen", "Owen", "Calm English support agent.", "male", EN],
  ["fa_nadia", "Nadia", "Warm English voice for healthcare and wellness.", "female", ["en", "en-US", "en-GB"]],
  ["fa_marcus", "Marcus", "Confident English voice for sales calls.", "male", ["en", "en-US"]],
  ["fa_mira", "Mira", "Multilingual service voice (English, Spanish, French, German).", "female", ["multi", "es", "es-419", "fr", "de", "en"]],
  ["fa_ravi", "Ravi", "Hindi and Indian English support voice.", "male", ["hi", "en-IN"]],
  ["fa_lena", "Lena", "Clear German customer service voice.", "female", ["de"]],
  ["fa_tomas", "Tomas", "Portuguese (Brazil) support voice.", "male", ["pt", "pt-BR"]],
];

const toVoice =
  (provider: string, previews: boolean) =>
  (r: Row, i: number): Voice => ({
    voice_id: r[0],
    provider,
    name: r[1],
    description: r[2],
    gender: r[3],
    languages: r[4],
    preview_url: previews ? chimeDataUri(i) : null,
    model_ids: [],
  });

export const VOICES: Record<string, Voice[]> = {
  elevenlabs: ELEVEN.map(toVoice("elevenlabs", true)),
  cartesia: CARTESIA.map(toVoice("cartesia", false)),
  fishaudio: FISH.map((r, i) => toVoice("fishaudio", i % 3 !== 2)(r, i)),
};

export function findVoice(provider: string, voiceId: string): Voice | undefined {
  return VOICES[provider]?.find((v) => v.voice_id === voiceId);
}
