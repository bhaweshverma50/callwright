# Recovered REST endpoints (axios base https://calldash-api-prod.azurewebsites.net/api)

```
DELETE  /agents/delete-agent/{id}
DELETE  /analysis/variables/{id}
DELETE  /annotations/calls/{id}
DELETE  /assets/audio-files
DELETE  /datasets/{id}
DELETE  /datasets/{id}/items/{id}
DELETE  /evals/evaluators/custom/{id}
DELETE  /knowledge-bases/{id}
DELETE  /knowledge-bases/agents/{id}/{id}
DELETE  /llms/delete-llm/{id}
DELETE  /phone-numbers/{id}
DELETE  /tests/cases/{id}
DELETE  /tools/{id}
DELETE  /whatsapp/channels/{id}
DELETE  /whatsapp/channels/{id}/caller-routes/{id}
GET     /agents/{id}/versions
GET     /agents/{id}/versions/{id}
GET     /agents/{id}/versions/{id}/diff/{id}
GET     /agents/{id}/versions/latest
GET     /agents/get-agent/{id}
GET     /agents/list-agents
GET     /analysis/variables/{id}
GET     /analysis/variables/agent/{id}
GET     /annotations/calls/{id}
GET     /assets/audio-files
GET     /auth/me
GET     /billing/balance
GET     /billing/transactions
GET     /calibration/evaluators
GET     /calibration/summary
GET     /calls/{id}
GET     /calls/{id}/flow-transitions
GET     /calls/{id}/latency-metrics
GET     /calls/{id}/recording-url
GET     /calls/{id}/turn-latencies
GET     /calls/agent/{id}
GET     /calls/status/{id}
GET     /calls/user/{id}
GET     /calls/user/{id}/paginated
GET     /calls/user/{id}/statistics
GET     /config/providers
GET     /dashboard/quality?{id}
GET     /dashboard/stats?{id}
GET     /datasets
GET     /datasets/{id}
GET     /datasets/{id}/items
GET     /evals/agents/{id}/config
GET     /evals/calls/{id}/evaluations
GET     /issues
GET     /issues/{id}
GET     /knowledge-bases
GET     /knowledge-bases/{id}
GET     /knowledge-bases/{id}/document-url
GET     /knowledge-bases/agents/{id}
GET     /knowledge-bases/check-duplicate
GET     /llms/get-llm/{id}
GET     /llms/list-llms
GET     /phone-numbers/
GET     /phone-numbers/{id}
GET     /pricing/catalog
GET     /review/queue
GET     /review/queue/summary
GET     /settings
GET     /simulator/experiments
GET     /simulator/experiments/{id}
GET     /simulator/experiments/{id}/runs
GET     /simulator/experiments/{id}/scorecard
GET     /simulator/runs
GET     /simulator/runs/{id}
GET     /templates
GET     /templates/{id}
GET     /templates/categories
GET     /tests/cases
GET     /tests/categories
GET     /tests/runs
GET     /tests/runs/{id}
GET     /tools/{id}
GET     /tools/llm/{id}
GET     /tools/predefined/
GET     /tools/predefined/{id}
GET     /usage/me
GET     /voices/cartesia
GET     /voices/elevenlabs
GET     /voices/fishaudio
GET     /whatsapp/channels
GET     /whatsapp/channels/{id}
GET     /whatsapp/channels/{id}/caller-routes
PATCH   /agents/{id}/versions/{id}/pin
PATCH   /agents/update-agent/{id}
PATCH   /analysis/variables/{id}
PATCH   /datasets/{id}
PATCH   /llms/update-llm/{id}
PATCH   /tests/cases/{id}
PATCH   /tests/results/{id}/status
POST    /agents/{id}/versions
POST    /agents/{id}/versions/{id}/restore
POST    /agents/create-agent
POST    /agents/duplicate-agent/{id}
POST    /ai/generate-prompt
POST    /analysis/variables
POST    /analytics/chat
POST    /assets/upload-audio
POST    /auth/logout
POST    /auth/password-reset
POST    /auth/register
POST    /auth/verify-token
POST    /billing/create-checkout-session
POST    /calldash/create
POST    /calldash/outbound
POST    /calls/create
POST    /datasets
POST    /datasets/{id}/evaluate
POST    /datasets/{id}/items
POST    /evals/calls/{id}/evaluate
POST    /evals/evaluators/custom
POST    /flows/generate
POST    /issues/{id}/apply
POST    /issues/{id}/auto-validate
POST    /issues/{id}/dismiss
POST    /issues/{id}/draft-fix
POST    /issues/{id}/validate
POST    /issues/detect
POST    /knowledge-bases
POST    /knowledge-bases/agents/{id}
POST    /llms/create-llm
POST    /phone-numbers/{id}/attach-inbound
POST    /phone-numbers/{id}/attach-outbound
POST    /phone-numbers/{id}/detach-inbound
POST    /phone-numbers/{id}/detach-outbound
POST    /phone-numbers/import
POST    /simulator/experiments
POST    /simulator/runs
POST    /tests/cases
POST    /tests/cases/bulk
POST    /tests/cases/generate
POST    /tests/runs
POST    /tools/create
POST    /tools/predefined/create
POST    /voice-commands/interpret
POST    /voice-commands/stream-token
POST    /voice-commands/transcribe
POST    /whatsapp/channels
POST    /whatsapp/channels/{id}/attach-agent
POST    /whatsapp/channels/{id}/caller-routes
POST    /whatsapp/channels/{id}/detach-agent
PUT     /annotations/calls/{id}
PUT     /calls/{id}
PUT     /evals/agents/{id}/config/{id}
PUT     /evals/evaluators/custom/{id}
PUT     /phone-numbers/{id}
PUT     /settings
PUT     /tools/{id}
PUT     /whatsapp/channels/{id}
```

# SPA routes
```
*
/
/agents
/agents/:agentId
/agents/:agentId/edit
/agents/:agentId/flow
/agents/:agentId/testing
/agents/new
/agents/new/flow
/agents/new/single
/agents/templates
/billing
/calibration
/calls
/calls/:callId/compare
/dashboard
/datasets
/datasets/:datasetId
/enterprise
/experiments
/experiments/:experimentId
/forgot-password
/issues
/issues/:issueId
/knowledge-base
/login
/phone-numbers
/pricing
/privacy-policy
/register
/review
/settings
/simulations
/simulations/:experimentId
/terms-of-service
```
