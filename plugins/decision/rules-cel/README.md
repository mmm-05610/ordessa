# ordessa-decision-rules-cel

Registers the `cel` rules engine under `ordessa.decision.rules`. The evaluator is
a closed CEL subset: literals, fact paths, `+ - * / %`, comparisons, `in`,
`&& || !`, list/map literals, `size`, `string`, `contains`, `startsWith`,
`endsWith`. No comprehensions, macros, regex, timestamps, user functions or I/O.
