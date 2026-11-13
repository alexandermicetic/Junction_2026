# AGENTS.md

## Project Overview

We are building a prototype for the Junction 2026 Valio Aimo Trusted Trade Agents challenge.

The project aims to create an open, secure and verifiable interface between external AI purchasing agents and Valio Aimo's B2B webshop and backend systems.

**Important: We are NOT building an AI purchasing agent. We are building the interface that allows external AI agents to interact with Valio Aimo.**

External agents are responsible for understanding customer requests, making purchasing decisions and selecting products.

Our system is responsible for exposing Valio Aimo's commerce capabilities safely and reliably.

## Core Responsibilities

The interface must support:

1. **Product discovery**
   - Search products.
   - Retrieve structured product information.
   - Support filtering by relevant product attributes.

2. **Price lookup**
   - Retrieve customer-specific fixed prices.
   - Return clear pricing information and units.

3. **Availability lookup**
   - Check product availability.
   - Retrieve available quantities and delivery information when supported.

4. **Order management**
   - Accept order requests from external agents.
   - Validate order contents.
   - Submit valid orders to the mock backend.
   - Return structured order confirmations and status information.

5. **Permissions and approvals**
   - Identify the requesting agent.
   - Check what actions the agent is authorized to perform.
   - Enforce purchasing limits and other restrictions.
   - Require human approval when necessary.

6. **Auditability**
   - Record important agent actions.
   - Record approval decisions.
   - Make it possible to understand why an order was accepted or rejected.

## Architecture Principles

- Build an API-first solution.
- Prefer open and interoperable standards.
- Keep the interface independent of any specific AI agent or LLM provider.
- Separate the interface from the simulated Valio Aimo backend.
- Keep business rules and authorization logic explicit.
- Use structured JSON requests and responses.
- Design the system so different external agents can integrate with it.
- Avoid unnecessary complexity.

## Security Principles

- Never connect to real Valio Aimo production systems.
- Use only the synthetic data and mock APIs provided for the challenge.
- Never commit API keys, passwords or other secrets.
- Store credentials in environment variables.
- Validate every incoming request.
- Never trust an external agent's claims about its own permissions.
- Verify authorization on the server side before performing actions.
- Never place an order without checking the required permissions and approval status.

## Development Guidelines

- Read existing code and documentation before making changes.
- Follow the existing project structure and conventions.
- Keep changes small and focused.
- Avoid introducing unnecessary dependencies.
- Do not duplicate existing functionality.
- Write clear, maintainable and well-documented code.
- Add tests for new functionality.
- Update documentation when API contracts or behavior change.

## API Guidelines

- Use consistent naming conventions.
- Define request and response schemas.
- Return meaningful HTTP status codes.
- Provide clear error responses.
- Document endpoints using OpenAPI.
- Make order creation safe against accidental duplicate submissions where possible.
- Distinguish between an order request, an approval request and a confirmed order.

## Testing Guidelines

Test at least the following scenarios:

- Successful product search.
- Successful price lookup.
- Product availability checks.
- Valid order submission.
- Unauthorized agent attempting to place an order.
- Order exceeding an agent's purchasing limit.
- Order requiring human approval.
- Rejected approval.
- Duplicate order submission.
- Product becoming unavailable before order submission.

Use synthetic test data only.

## Collaboration Guidelines

This project is developed by two developers.

- Use separate Git branches for individual tasks.
- Keep pull requests focused.
- Avoid modifying the same files simultaneously where possible.
- Review changes before merging into the main branch.
- Keep shared API contracts documented and up to date.

## Codex Instructions

Before implementing a new feature:

1. Inspect the relevant existing code.
2. Explain the proposed implementation briefly.
3. Identify affected files.
4. Consider security and authorization implications.
5. Implement only the requested scope.
6. Run relevant tests.
7. Report what changed and what remains incomplete.

Do not invent mock API endpoints or behavior. Inspect the provided API documentation before implementing integrations.

If requirements are unclear, state assumptions and ask questions rather than silently making important architectural decisions.
