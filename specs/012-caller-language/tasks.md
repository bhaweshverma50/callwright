# Tasks: caller language (012)

- [x] T001 Contract `contracts/caller_language.yaml`, `features.txt`; 002 `advanced.language_switching` and TTS model `languages`; 003 `RuntimeConfig.language_options`, `caller_language`, `language_switched` system event; 008 spec `language_options`; `make contracts`, `pnpm gen:api`
- [x] T002 Default voice: `eleven_multilingual_v2` in both catalogs, seed templates, web defaults; ElevenLabs adapter maps expressiveness to stability, style and speaker boost
- [x] T003 Speech catalog: TTS model languages and multilingual fallbacks; `caller_language/options.py`
- [x] T004 Agent config: schema, upcast, defaults, validation, labels, version diff order
- [x] T005 Migration `s012_0001`: `caller_preferences`, `call_languages`, RLS
- [x] T006 Claim: `language_options`, `caller_language` from the saved preference, start row; textsim specs carry the options
- [x] T007 Internal `POST /v1/internal/calls/{id}/language`; public list, delete, call view
- [x] T008 Worker: `set_language` tool, override staging, reply-language instruction, call start in the saved language, translated greeting with fallback
- [x] T009 Textsim: set_language switches instructions, no report
- [x] T010 Web: editor control, call drawer card, MSW mocks, version labels, default stack price
- [x] T011 Tests: API `tests/integration/test_caller_language.py`, `tests/unit/caller_language`; worker `test_set_language.py`, `test_tts_elevenlabs.py`, `tests/harness/test_textsim_language.py`; web editor and drawer tests
