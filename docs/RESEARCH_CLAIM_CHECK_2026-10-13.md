# External claim checks — October 13, 2026

Primary sources were checked during the local repository audit. These checks do
not establish market size, customer demand, certification or a legal opinion.

| Historical claim | Verified position | Primary source |
| --- | --- | --- |
| Kong only routes generic JSON | Incorrect: its documentation describes MCP tool ACLs and A2A routing | [MCP access rules](https://developer.konghq.com/ai-gateway/entities/ai-mcp-server/), [AI Gateway](https://developer.konghq.com/ai-gateway/) |
| Bedrock Guardrails only apply to Bedrock-hosted models | Incorrect: ApplyGuardrail can assess text independently, including external-model applications | [Independent API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html), [AWS example](https://aws.amazon.com/blogs/machine-learning/implement-model-independent-safety-measures-with-amazon-bedrock-guardrails/) |
| All EU high-risk obligations universally apply in mid-2026 | Incorrect as a universal timetable: Commission guidance records Annex III December 2, 2027 and Annex I August 2, 2028; other obligations have different dates | [Commission timeline](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai), [AI Omnibus entry into force](https://digital-strategy.ec.europa.eu/en/news/ai-omnibus-enters-force) |
| Python is proven to be the limiting factor | Unsupported without equivalent service-path benchmarks; SQL, crypto, remote latency and contention must be measured separately | Repository benchmark scripts and exact-source audit evidence |
| Four products, large ARR/TAM, insurance savings or settlement certification are validated | Unsupported: the source implements one shared engineering foundation; independent commercial/operational evidence remains open | [Four-product gates](FOUR_PRODUCT_EXECUTION_GATES_2026.md) |

Cryptographic signatures authenticate claims and bindings. They do not alone
prove external fulfillment, legal compliance or universal exactly-once effects.
Keep the limited protocol contract and destination trust assumptions explicit.
