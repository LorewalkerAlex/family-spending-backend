# Publish typed read-model changes

The single writer publishes one immutable household snapshot composed of independent finance, automation, and feedback subtrees. Commands return a typed `ReadModelChange`, and a projector replaces or rebuilds only the affected subtree; this keeps atomic reads while preventing unrelated use cases from carrying one broad state object or requiring an event bus.
