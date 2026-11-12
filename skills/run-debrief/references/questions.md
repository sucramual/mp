# Questions

The closed-book questions check that the owner can explain the run without the page. They follow the SOLO scale that `/hard-cheese` and `/understand-pr` use, at the level of the whole run.

## Write the questions

Write three or four questions. Cover at least three of these kinds:

| Kind | Asks the reader to | Example shape |
| --- | --- | --- |
| Why this shape | Explain a decision against its strongest alternative | "Why does X own the lifecycle, and not Y?" |
| Mechanism | Trace a path through the parts that the run built | "What happens, in order, when <trigger>?" |
| Failure | Explain a learning moment and its cause | "Why did <first attempt> fail, and what did the fix change?" |
| Boundary | Say what the proof does not cover | "Which check is unit only, and what could still break live?" |

- Ground each question in one source: a decision, a learning moment, or a goal check on the page.
- Ask for a cause, not a name. "Which PR added X?" tests recall. "Why did X need its own PR?" tests understanding.
- Put no answer in the question.

For each question, write the answer criteria in a folded block, not a model answer:

- **Weak (Unistructural):** names one element or outcome.
- **Pass (Multistructural):** names the relevant facts: state, steps, or constraints.
- **Strong (Relational):** connects those facts causally, and says what would break without the chosen shape.

Under the criteria, link the page section and the source that hold the answer.

## Grading

Marcus answers in chat, without the page open. Grade each answer against its criteria.

1. Give the level: Weak, Pass, or Strong.
2. Name the correct facts that the answer gives.
3. Name the one causal link that is missing, and the section or source to reread. Do not write the full answer.
4. When he asks for the full answer, or after a second attempt, give it with its source.

After the last answer, give one line: the number of answers at Pass or better, and the concept to reread first when one is below Pass.
