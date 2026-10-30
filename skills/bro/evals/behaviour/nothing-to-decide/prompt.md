---
max_turns: 4
allowed_tools: [Skill]
---

What do I need to decide here?

Context from this session: the checkout test failed once on main this morning. The retry passed. I found that a shared fixture leaks a cart between tests, and the fix is already in review with an approval. Nothing is blocked, and no release is waiting. A second leak is possible but I have not confirmed one.
