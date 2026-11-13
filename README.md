# Valio Aimo – Trusted Trade Agents

An open and verifiable interface for AI-powered B2B purchasing agents.

## About the project

This project is a prototype built for Junction 2026 in collaboration with Valio Aimo.

Our goal is to demonstrate how external AI purchasing agents can safely interact with a foodservice wholesaler's systems to search products, compare prices and availability, and place orders autonomously within predefined permissions.

Instead of building another webshop or chatbot, we are exploring a trusted interface between external purchasing agents and wholesale systems.

## The problem

Traditional B2B foodservice ordering requires significant manual work.

We explore how AI agents can:
- Find suitable products.
- Retrieve customer-specific prices.
- Check product availability and delivery dates.
- Create orders.
- Request human approval when necessary.
- Explain and document their decisions.

## Our solution

We are building a prototype consisting of:

- **Purchasing agent:** Understands customer requests and makes purchasing decisions.
- **Trade API:** Provides structured access to products, prices, availability and orders.
- **Permission system:** Defines what an agent is allowed to do.
- **Approval workflow:** Ensures that sensitive purchasing decisions receive human approval.
- **Audit log:** Records what the agent did and why.

## Example use case

A restaurant asks:

"I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability."

The agent searches the catalog, checks prices and availability, proposes a suitable option and either places the order within its permissions or requests human approval.

## Architecture

*Architecture diagram coming soon.*

## Tech stack

To be defined as implementation progresses.

Our design priorities:
- Open standards.
- Structured APIs.
- Verifiable permissions.
- Secure agent-to-business interaction.
- Explainable decisions.

## Getting started

*Setup instructions will be added once the initial implementation is ready.*

## Project structure

```text
/
├── README.md
├── AGENTS.md
├── docs/
├── api/
├── agent/
├── backend/
├── frontend/
└── tests/
```

## Team

Two-person development team building a prototype for Junction 2026.

## Scope and security

- This project uses synthetic data and simulated backend systems.
- No production systems or confidential business data are accessed.
- API credentials and secrets must be stored in environment variables and never committed to Git.

## Status

Early-stage prototype. Architecture and API contract are being defined.
