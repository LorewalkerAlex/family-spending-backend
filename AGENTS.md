# Agent Guide

> **Role:** Canonical entry point for working in this repository.
>
> Read this document first when entering the project.
>
> Repository-specific purpose, architecture decisions, scope, and implementation phases are defined in [`README.md`](./README.md). Read it after this guide before making project changes.
>
> This guide defines the engineering principles and working model used to understand, change, verify, and continue the project.
>
> It does not assume a particular documentation structure, architecture, technology stack, repository layout, development methodology, or delivery workflow. Discover project-specific answers from the repository itself.

---

# Principles

## 1. Reality

Work from the current project reality.

The repository is the durable representation of the project. Conversations, handoffs, screenshots, issues, previous-session summaries, and external descriptions may provide useful context, but they do not replace current repository evidence when that evidence is available.

Before relying on remembered or supplied project facts, verify them against the current project when practical.

Distinguish clearly between:

```text
Target State
what should be true

Current State
what is true now

Active Gap
the meaningful difference between them
```

Do not treat existing implementation as automatically defining intended behavior.

Do not describe intended or planned behavior as already implemented.

---

## 2. Context

Understand before changing.

Every change exists inside a larger system of goals, rules, responsibilities, dependencies, conventions, and previous decisions.

Build the smallest reliable mental model sufficient for the task.

Do not read the entire repository indiscriminately, but do not make isolated changes without understanding the responsibility they affect.

Follow relevant relationships outward until the impact of the task is understood well enough to act safely.

---

## 3. Discovery

Discover the project rather than imposing a predefined model on it.

When entering an unfamiliar repository, determine how the project expresses:

- purpose and intended behavior;
- important terminology and rules;
- architecture and responsibility;
- persistent or shared state;
- current implementation status;
- development and validation practices;
- important decisions and constraints;
- release or delivery behavior where relevant.

These answers may live in documentation, code, configuration, schemas, tests, generated artifacts, history, or other project-specific mechanisms.

Do not assume particular filenames, directories, layers, or document types exist.

Prefer explicit project guidance when it exists.

---

## 4. Authority

One fact should have one canonical authority.

Other representations may implement, derive, present, explain, cache, test, or verify that fact, but should not silently create competing definitions.

When multiple sources discuss the same subject, determine their intended relationship before treating them as equivalent.

When sources disagree, do not immediately choose one.

First determine whether the difference represents:

- different responsibilities;
- stale information;
- an implementation defect;
- an intentional transition;
- an unresolved decision;
- generated or derived state;
- historical evidence.

Place new durable knowledge at the boundary that owns it.

---

## 5. Ownership

Responsibilities should have clear owners.

A rule, mechanism, decision, or piece of volatile knowledge should live at the smallest coherent boundary capable of owning it.

When a problem becomes visible somewhere, determine whether that location owns the cause or merely observes its effects.

Prefer fixing the earliest appropriate owner of the violated rule.

Do not create a parallel implementation merely because the established owner is less convenient to reach.

When several parts of the system independently make the same decision, look for the responsibility that should own that decision once.

---

## 6. Invariants

Reason from rules rather than examples.

For a defect or inconsistency, identify:

- what should always be true;
- why the current system allowed it to become false;
- which responsibility should guarantee it.

Prefer preventing invalid or ambiguous states over compensating for them after they appear.

Do not add a special case solely for one failing example when the real problem is a violated invariant or incomplete model.

Repeated edge-case branches around the same decision are evidence that the underlying abstraction, state representation, or ownership boundary may need correction.

---

## 7. Coherence

Optimize for the health of the system, not the convenience of the current edit.

A successful change solves the intended problem while preserving or improving the consistency of the surrounding project.

Prefer the smallest **coherent** change over the smallest textual diff.

A coherent change may touch several consumers when they all depend on the same corrected responsibility.

Do not solve one caller, page, test, or historical example by introducing contradictory behavior elsewhere.

---

## 8. Simplicity

Complexity must earn its place.

Prefer solutions that are easy to understand, explain, maintain, verify, and remove.

Avoid:

- speculative abstractions;
- unnecessary indirection;
- premature generalization;
- thin wrappers with no meaningful ownership;
- new dependencies without demonstrated value;
- mechanisms designed primarily for hypothetical future needs.

Simplicity does not mean preserving a weak model.

When the underlying structure is wrong, correcting it may be simpler in the long term than accumulating local workarounds.

---

## 9. Reuse

Reuse established knowledge and mechanisms.

Before creating something new, inspect the project for existing:

- concepts;
- types;
- abstractions;
- components;
- utilities;
- workflows;
- validators;
- state owners;
- test helpers;
- integration patterns.

Reuse responsibilities, not merely similar-looking code.

Two implementations that look alike may represent different concepts.

Two very different surfaces may depend on the same underlying responsibility.

---

## 10. Boundaries

Respect established responsibility and dependency boundaries.

Understand why a boundary exists before crossing, bypassing, or replacing it.

Prefer changing the owner of a responsibility over teaching every consumer to compensate for the owner's limitations.

Do not leak lower-level implementation knowledge outward merely because it is available.

Do not move high-level rules into low-level mechanisms for convenience.

When a task repeatedly fights an existing boundary, determine whether:

```text
the caller is using it incorrectly
or
the boundary itself no longer represents the system well
```

Correct the appropriate side.

---

## 11. Target State

Work toward the intended system, not merely the inherited one.

Existing code, tests, and structure are valuable evidence and should be reused when appropriate, but historical implementation does not automatically define the future design.

Likewise, an aspirational design should not erase useful working mechanisms without justification.

Determine what should remain, what should change, and why.

Avoid preserving accidental complexity solely because it already exists.

---

## 12. Proportionality

Engineering effort should match real value and real risk.

Testing, defensive behavior, abstraction, performance work, migration machinery, compatibility support, observability, and operational complexity should be justified by actual requirements and evidence.

Do not build large-system solutions for small-system problems.

Do not under-engineer boundaries where failure would cause significant data loss, incorrect behavior, difficult recovery, or broad downstream impact.

Use evidence to decide where rigor belongs.

---

## 13. Evidence

Ground project claims in evidence.

Different questions require different evidence.

Examples include:

- project authorities for intended behavior;
- implementation for current behavior;
- tests for established contracts;
- runtime behavior for integration facts;
- schemas and persisted data for representation facts;
- version history for historical questions;
- external authoritative sources for external constraints.

Distinguish:

```text
verified fact
reasonable inference
working assumption
unresolved question
```

Do not present an assumption as a verified project fact.

Never claim that a test, command, build, inspection, search, or verification succeeded unless it was actually performed successfully.

---

## 14. Verification

Verify the responsibility that changed.

Validation should follow actual impact rather than a fixed ritual.

A bounded local change may require only focused evidence.

A shared contract, invariant, schema, dependency boundary, or widely consumed mechanism may require broader verification.

Determine:

- what behavior changed;
- who consumes it;
- what could regress;
- what evidence would demonstrate correctness.

Regression tests should protect the underlying rule rather than only reproduce the reported input.

When useful, include neighboring valid cases and meaningful boundaries so a one-off patch cannot satisfy the test accidentally.

If verification reveals a wider consumer graph than expected, update the model of the problem and broaden the work accordingly.

---

## 15. Change Discipline

Keep changes focused and intentional.

Every change should have a clear reason, responsibility, and expected outcome.

Avoid mixing unrelated:

- cleanup;
- refactoring;
- renaming;
- formatting;
- dependency changes;
- architectural changes;
- behavioral changes.

Do not broaden a task merely because nearby code could also be improved.

At the same time, do not leave the system internally inconsistent merely to keep the diff artificially small.

Preserve unrelated project state.

Never destroy unfamiliar or uncertain work simply to obtain a clean starting point.

---

## 16. Evolution

Projects evolve.

Architecture, documentation, abstractions, conventions, and workflows encode accumulated knowledge and should be respected, but they are not immutable.

When evidence shows that an existing structure no longer represents the project correctly, improve the underlying model rather than building permanent workarounds around it.

Foundational changes should be deliberate.

The broader the responsibility being changed, the stronger the understanding and evidence required.

---

## 17. Continuity

The project should remain understandable without the current conversation.

A future session should be able to reconstruct the relevant project state from durable project material.

Important knowledge should not exist only in:

- chat history;
- handoff messages;
- personal recollection;
- temporary explanations.

When work changes an enduring project fact, record that fact through the project's established durable mechanism.

A handoff may identify where to resume, but it should point back to project truth rather than become a competing source of truth.

---

# Working Model

Use the following model when entering a project or beginning meaningful work:

```text
Orient
↓
Understand
↓
Locate Responsibility
↓
Change
↓
Verify
↓
Record
```

This is a reasoning model, not a mandatory mechanical checklist.

The depth of each stage should be proportional to the task.

---

## Orient

Establish enough context to know where you are.

Discover:

- what the project is;
- what it is currently trying to achieve;
- how the repository is organized;
- how the project records authoritative knowledge;
- what its current durable state is;
- which part of the project the current task concerns.

Follow project-provided entry points and conventions when they exist.

Do not require the user to restate information that can be established reliably from the project.

---

## Understand

Determine what should be true and what is true now.

Identify the relevant intent, rules, existing design, implementation behavior, constraints, and evidence.

Resolve material ambiguity from existing project knowledge before inventing a new answer.

For bugs and regressions, identify the violated rule before choosing the fix.

For new behavior, understand which existing responsibilities it extends before creating new ones.

---

## Locate Responsibility

Determine where the relevant fact or behavior belongs.

Inspect enough producers and consumers to understand the impact of changing that responsibility.

Ask whether the visible failure is:

```text
the source of the problem
or
a downstream symptom
```

Prefer changing the true owner.

Reuse established mechanisms where they already represent the required responsibility.

---

## Change

Make the simplest coherent change that moves the system toward the intended state.

Follow surrounding project conventions.

Preserve established behavior outside the requested scope.

Avoid duplicate authority and parallel mechanisms.

When changing a shared contract, carry the change through the consumers that depend on that contract rather than leaving inconsistent interpretations behind.

---

## Verify

Gather sufficient evidence that the resulting system behaves as intended.

Verify both:

```text
the changed rule
and
the important consequences of that rule
```

Choose verification according to responsibility, impact, and project conventions.

Use broader validation when the affected consumer graph cannot be bounded confidently.

Review the final change itself for unintended duplication, stale logic, inconsistent naming, unused mechanisms, and unrelated modifications.

---

## Record

Leave durable project knowledge aligned with the resulting system.

If implementation changed to satisfy an already-established rule, avoid unnecessarily rewriting higher-level intent.

If the work changes an enduring rule, responsibility, constraint, or project state, update the project mechanism that owns that knowledge.

The repository after the work should make the resulting state understandable to a future session.

---

# Questions

The following questions guide reasoning. They are not a requirement to produce written answers to every item.

Use only those relevant to the task.

## Orientation

- What is this project?
- What is its current state?
- How does it organize knowledge?
- Where does it expect a new contributor or session to begin?
- What part of the system does this task concern?

## Authority

- Where is the relevant truth defined?
- Which sources are authoritative?
- Which are derived, explanatory, generated, historical, or evidentiary?
- Are apparently conflicting sources actually responsible for different things?

## Intent

- What should be true?
- What is true now?
- What is the meaningful difference?
- Is the task changing intent, correcting implementation, or both?

## Responsibility

- What owns the relevant behavior?
- Where is that responsibility currently implemented?
- Which consumers depend on it?
- Does an existing mechanism already represent the concept?
- Is the observed failure the cause or only a symptom?

## Design

- What invariant or contract should hold?
- What is the simplest coherent model?
- Does the proposed solution introduce duplicate authority?
- Is new complexity justified by current needs?
- Does the change improve the system rather than only the reported example?

## Change

- What is the smallest coherent change?
- What existing mechanisms can be reused?
- Which consumers need to change together?
- What should explicitly remain unchanged?

## Verification

- What evidence would demonstrate correctness?
- Which neighboring cases or boundaries matter?
- How far does the affected responsibility propagate?
- Is focused verification sufficient, or is broader validation required?

## Continuity

- Did any durable project fact change?
- Is that fact recorded at the correct authority?
- Is important information trapped only in the current conversation?
- Could another session continue the work from the repository alone?

---

# Completion

Completion depends on the requested boundary.

Investigation, design, implementation, validation, publication, deployment, and release are distinct forms of completion.

Do not imply that work has reached a boundary that was not actually reached.

In general, a meaningful engineering change is complete when:

```text
the intended outcome is understood
↓
the correct responsibility owns the solution
↓
affected consumers remain coherent
↓
sufficient evidence supports the result
↓
durable project knowledge reflects the resulting state
↓
a future session can continue from the project itself
```

The goal is not merely to finish the current task.

The goal is to leave the project in a state that remains correct, understandable, maintainable, and continuable after the current session ends.
