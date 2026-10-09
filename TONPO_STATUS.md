# Tonpo Status

## A) What I already have

- The Tonpo Python application and existing Gateway-based architecture.
- Installed Python SDK: `tonpo==1.0.4`.
- Python client integration for Gateway health, user/account provisioning, account data, prices, positions, orders, and position management.
- Existing fail-closed execution boundary when authoritative symbol constraints are unavailable.
- Android phone with Termux.
- Local automated test and dry-run environment.

## B) What is missing

- A real Tonpo Gateway deployment.
- The Tonpo Bridge C++ DLL.
- The MQL5 EA/bridge component.
- An MT5 terminal environment.
- A broker demo account and its MT5 login/server details.
- An authoritative Gateway capability for broker symbol specifications.
- A documented Gateway server/Bridge/EA version compatible with SDK 1.0.4.
- A safe external Gateway health, metadata, demo-order, and reconciliation test.

## C) Where missing components must come from

- The project README identifies the Python SDK repository as `https://github.com/TonpoLabs/tonpo-py`.
- Installed SDK metadata identifies `https://cipherbridge.cloud` as its homepage and describes Tonpo Gateway as proprietary/self-hosted.
- The SDK documentation describes the stack as Rust Gateway → Tonpo Bridge C++ DLL + MQL5 EA → MT5 terminal → broker.
- The repository and installed package contain no Gateway server distribution, Bridge binary, MQL5 EA, Windows installer, Docker image, Linux package, or Gateway download instructions.
- Therefore the Gateway/Bridge/EA must be obtained from the Tonpo Gateway provider/maintainer; the exact acquisition channel and commercial availability are not established by this project.
- A broker demo account must come from a broker that supports MetaTrader 5.

## D) Is a Windows VPS actually required?

- For the documented self-hosted architecture, the MT5 terminal plus the C++/MQL5 bridge must run on an appropriate Windows environment. The installed SDK documentation explicitly describes Windows VPS cold-start behavior.
- No supported Linux, Android, Docker-only, or Termux Gateway/MT5 alternative was found locally.
- A Windows VPS is therefore required for the self-hosted MT5-side path unless the Gateway provider supplies a supported hosted Gateway/MT5 service. That hosted option was not verified.
- The Tonpo bot can remain elsewhere, but a phone-only Termux environment cannot itself provide the documented MT5 terminal/Bridge runtime.

## E) Cheapest safe path to a demo environment

1. Contact the Tonpo provider through the SDK’s documented provider channels and ask for the official Gateway server distribution or hosted Gateway option, Bridge/EA package, supported versions, installation guide, symbol-specification capability, and pricing.
2. Obtain a low-cost Windows VPS only after confirming the official deployment requirements.
3. Open a broker demo account, never a funded/live account.
4. Install MT5 and the official Gateway/Bridge/EA on that VPS according to provider instructions.
5. Keep Tonpo `TRADING_DRY_RUN=true`; test health, account connection, symbol metadata, rejection behavior, and reconciliation before any consideration of activation.

No purchase, installation, credential use, or external contact was performed.

## F) What to do next from Android only

- Use the phone browser or Telegram/email to contact the Tonpo provider and request the official Gateway/Bridge/EA acquisition and deployment instructions.
- Ask specifically whether they provide a hosted Gateway or require a Windows VPS, and whether the Gateway exposes authoritative MT5 symbol specifications.
- Ask the broker for a demo account only; do not submit credentials here.
- Do not attempt to run MT5, the MQL5 EA, or the C++ Bridge in Termux.
- Return only the provider’s documented, non-secret deployment details before changing application integration.

## G) What must not be done

- Do not install random Gateway binaries or unofficial bridges.
- Do not download unknown executables, MQL5 files, or containers.
- Do not invent Gateway endpoints or SDK methods.
- Do not bypass the Gateway with direct MT5 IPC.
- Do not use a live broker account.
- Do not paste tokens, passwords, API keys, or MT5 credentials into chat.
- Do not change `TRADING_DRY_RUN` from `true`.
- Do not treat local mocks as external certification.

## Verification and current gate

- `python -m pytest -q`: passed; deprecation warnings only.
- `python -m compileall -q .`: passed.
- `git diff --check`: passed.
- No external services were contacted.
- No application code was modified; only this status ledger was updated.
- `TRADING_DRY_RUN=true`.
- BROKER EXECUTION GATE: BLOCKED — external Gateway/Bridge/MT5 infrastructure and official acquisition/deployment details are unavailable.

## Forensic reconstruction: original execution architecture

### A) Original Telegram execution path

The repository's original Telegram path is still structurally present:

`Telegram channel signal or /trade`
→ `UnifiedSignal`
→ `SignalPipeline.process()`
→ authentication, subscription, news, risk, idempotency, and emergency-stop checks
→ `TradeExecutor.execute_trade()`
→ `ExecutionProvider`
→ `GatewayManager.get_connection()`
→ `TonpoClient.for_user(..., api_key)`
→ `TonpoConnectionAdapter`
→ installed Tonpo SDK order method
→ external Tonpo Gateway
→ Tonpo Bridge / MQL5 EA
→ MT5 terminal
→ broker.

Registration provisions the external Gateway account through the SDK, waits for the account to become active, and stores the returned routing identifiers. The application does not contain an MT5 client or a broker-direct fallback.

### B) Gateway origin

Git history contains one commit only and no deleted Gateway or MT5-side files. The repository contains the Python client adapter and declares `tonpo==1.0.4`, but no Gateway server, Bridge DLL, MQL5 EA, MT5 terminal package, Windows installer, or deployment bundle. The committed configuration contains only a placeholder `GATEWAY_HOST`; no real endpoint is recoverable from history. The installed SDK metadata describes the Gateway as proprietary/self-hosted and documents the external Rust Gateway → C++/MQL5 Bridge → MT5 stack.

Therefore the original Gateway was an external deployment dependency, not a component included in this repository. No secret or credential value was printed or recovered.

### C) Current state versus the original Telegram system

TradingView now enters the secure FastAPI webhook, passes authentication, timestamp/schema validation, Redis rate limiting, and idempotent signal processing, then reaches the same `SignalPipeline` → `TradeExecutor` → `ExecutionProvider` → Tonpo SDK → external Gateway path. No disconnected TradingView-to-Gateway link was found.

The current implementation adds stricter fail-closed controls, durable signal and execution protection, news checks, and an authoritative broker-symbol constraint requirement. Because SDK 1.0.4 exposes price data but no authoritative symbol contract metadata, live execution is intentionally blocked rather than using the legacy hardcoded sizing path. This is a safety correction, not a Gateway replacement.

The old local webhook compatibility handler does not create a second execution path; the active TradingView ingress is the web application route.

### D) Exact blocker

**No usable original Gateway runtime/configuration can be recovered or verified from the repository; the Gateway is an external deployment dependency and this environment has no verified Gateway/MT5 demo endpoint. Consequently the original path cannot be externally demonstrated.**

`TRADING_DRY_RUN=true` is an intentional safety condition, not a defect. The missing symbol-contract capability remains a deliberate fail-closed requirement before any live execution could be considered.

### E) Minimum safe fix

Obtain the official external Gateway/Bridge/EA deployment and a broker demo environment through the provider's documented channel, then configure the existing `GATEWAY_HOST` contract without changing the architecture. The Gateway/SDK contract must also provide authoritative symbol constraints required by the current safety checks. No invented endpoint, SDK method, broker default, or hardcoded constraint is acceptable.

### F) TradingView status

TradingView signals already reach the same original execution path after the secure intake and deterministic pipeline checks. No application-code change was required for this forensic task.

### G) Final release gate

The original execution architecture is preserved, but the broker execution gate remains blocked. Before MT5 demo certification, the external Gateway/Bridge/EA and MT5 demo environment must be supplied and verified, including authoritative symbol metadata, order response handling, unknown-result reconciliation, and dry-run-safe integration tests. No real order was submitted.

