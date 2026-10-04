# Glossary

Every term this repo uses with a precise meaning, where the word comes from, and — the part worth
reading — **what it does not mean here**. Linked from the README so the prose can stay short.

Entries are alphabetical. Each is three lines at most: what it means here, its lineage, and the
confusion it is most often mistaken for.

---

## Battle

Two strategies run over the same cases with the same evaluators, and the scores are compared.

**Why it exists.** Reasoning quality is subjective — there is no correct answer to diff against,
so "better" is an empirical question, settled head-to-head like a sport rather than asserted.

⚠️ **A battle without a [noise floor](#noise-floor) is vibes with a number attached.** A delta
that does not clear the replicate is not a result.

## Bindable

Anything a [strategy](#strategy) must supply an implementation for: a `StepSpec`, or a
`TransformEdgeSpec` left open.

⚠️ **Not the same as "a box in the design".** A join and a decision are declared boxes that take
no implementation — that axis is `NodeSpec`. Conflating the two is how a join ends up demanding
an implementation.

## Coherence

The parts hang together into a whole: every value goes somewhere, every box participates, every
role is filled.

**Lineage.** In epistemology a coherent set of beliefs is *mutually supporting*, not merely
non-contradictory — which is a stronger property than [consistency](#consistency).

⚠️ **This library checks that the parts CONNECT, not that they support a conclusion.** A step
that returns its input untouched passes every rule and does nothing. Structure is provable;
support is only measurable, which is what a [battle](#battle) is for.

## Consistency

No two statements contradict. A contradiction is **local** — you can point at both halves.

⚠️ **Consistent is weaker than [coherent](#coherence), and the gap is the whole problem.** Three
unrelated true facts are perfectly consistent and completely incoherent. An inconsistency usually
crashes; an incoherence **runs and returns the right shape**, which is why it is the expensive
one and why it is the failure an AI coding agent produces.

## Declaration layer

The workflow's shape written as **data** — tuples of specs in a class body — rather than as code.
Nothing executes, so `coherence_check()` and `diagram()` can read it before a single step exists.

See [deep embedding](#deep-embedding) for why this is the precondition for everything else.

## Deep embedding

A DSL whose constructs build a **data structure** representing the program, rather than directly
performing the behaviour (which is a *shallow* embedding).

**Why it matters here.** Checks, diagrams and diffs exist because there is an artifact to read;
none of them is possible over a shallow embedding.

⚠️ **Battles are the exception, and the distinction is the interesting part.** `compare_graphs()`
runs two ALREADY-BUILT graphs and needs no declaration — so comparing is possible without one.
What the artifact buys is that `eval_battle` takes exactly ONE `spec`, so both arms provably
render from the same design. The embedding does not enable the battle; it enables the *fairness*.

⚠️ **The price is expressiveness.** A deep embedding can only say what its vocabulary has words
for; `docs/parity.md` is that bill, itemised.

## Design rule check (DRC)

Chip design's name for this activity: read a layout and report what could not possibly be right,
before anything is fabricated.

**The close cousin is ERC, Electrical Rule Check**, which checks connectivity rather than
geometry, and its failures map onto ours almost exactly:

| ERC | here |
|---|---|
| floating / undriven net | a node unreachable from START |
| dangling output | a node that cannot reach END |
| two drivers on one net | two edges feeding one step |

**LVS (Layout Versus Schematic)** — does the built thing match the design? — has no equivalent
here, deliberately: every graph is wired from `edges`, so the two cannot disagree. A check that
cannot fail is decoration.

## Finding

One thing a check found, as a `CoherenceFinding` — a `str` subclass, so it reads as the sentence
it is while carrying `check`, `about` and `blocking`.

⚠️ **"Finding" covers two different outcomes on purpose**: a defect, and a
[stated gap](#stated-gap). "Violation" would be wrong for the second.

## Noise floor

`eval_battle` scores one strategy **against itself**. That replicate is the bar a real delta has
to clear.

⚠️ **Without it, every A/B is theatre.** A difference inside the noise is not a difference.

## Soundness (workflow nets)

Van der Aalst's property of a workflow net: it can always complete, completes properly, and has
no dead transitions. Its two classic violations are exactly two of our rules — **lack of
synchronization** (a fan-out with no join) and **deadlock** (a fan-in with no split).

⚠️ **Our checks are STRUCTURAL approximations, not a soundness proof.** Soundness is behavioural
and generally needs state-space analysis. Ours are cheap, decidable, and catch the common unsound
shapes — which is a different and smaller claim.

## Stated gap

A finding beginning `NOT CHECKED — …`: the check looked and could not reach a verdict. It does
not block `render()`.

⚠️ **A stated gap is not a pass.** `NOT CHECKED` and `0 FOUND` must never render the same — an
audit that implies a check it skipped is the exact failure this library exists to catch.

## Static semantics

The rules a program must satisfy beyond being syntactically valid, checkable without running it.
Compilers call the phase **semantic analysis**; its failures are static semantic errors.

Same thing as [well-formedness rules](#well-formedness-rule); the word depends on whether you
came from compilers or from modeling.

## Strategy

One complete set of implementations for a design — every [bindable](#bindable) filled. The unit a
[battle](#battle) compares.

⚠️ **Partial strategies are refused**, including for stages that do not change. A strategy that
binds only what differs makes "what varies between these arms" unanswerable without reading both
files.

## Substitutability

A subgraph is a valid implementation of a node only when its public boundary matches the role it
fills. Liskov's rule, applied to a graph rather than a class.

## Variation point

A place the design deliberately leaves open for a strategy to fill. Borrowed from software
product-line engineering.

⚠️ **Defined by the design leaving the implementation open, not by where it is declared** — a
`TransformEdgeSpec` with no `apply=` is a variation point and it lives in `edges`.

## Well-formedness rule

A static constraint a declaration must satisfy. UML's specification used *Well-Formedness Rules*
as section headings, written in OCL over the metamodel.

⚠️ **Not an "invariant" in the strict sense.** An invariant is preserved across state changes — a
loop invariant, a class invariant. These are checked once, against a static artifact. "Structural
invariant" is common usage and nobody will blink, but *constraint* is the accurate word.
